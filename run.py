import argparse
import logging
from pathlib import Path
import pickle
import time

from expman import Experiment
import numpy as np
import pandas as pd
from tqdm import trange

import surrogate
from utils import get_dataset, nice_logspace, compute_recalls


def configure_logging(log_path):
    stream_handler = logging.StreamHandler()
    stream_handler.setLevel(logging.INFO)

    logging.basicConfig(
        level=logging.DEBUG,
        format='%(asctime)s [%(levelname)s] %(module)s.%(funcName)s:%(lineno)d - %(message)s',
        handlers=[logging.FileHandler(log_path, mode='a'), stream_handler]
    )


def load_or_train_index(x, train_params, trained_index_path, train_metrics_path, force=False):
    if not Path(trained_index_path).exists() or force:
        # create index
        d = x.shape[1]
        index_type = train_params.pop('index_type')
        index = surrogate.index_factory(d, index_type, train_params)

        # train index
        index_repr = ' '.join([f'{k}={v}' for k, v in train_params.items()])
        logging.info(f'Training index: {index_type}({index_repr})')

        train_time = time.time()
        index.train(x)
        train_time = time.time() - train_time
        logging.info(f'Done in {train_time} s.')

        # save trained index
        logging.info(f'Saving trained index: {trained_index_path}')
        with open(trained_index_path, 'wb') as f:
            pickle.dump(index, f)

        train_metrics = pd.DataFrame({
            'train_time': train_time,
        }, index=[0])
        train_metrics.to_csv(train_metrics_path, index=False)

    else:
        logging.info(f'Reading pretrained index from: {trained_index_path}')
        with open(trained_index_path, 'rb') as f:
            index = pickle.load(f)

        train_metrics = pd.read_csv(train_metrics_path)
    
    return index, train_metrics


def load_or_build_index(index, x, build_params, built_index_path, build_metrics_path, index_batch_size, force):
    if not Path(built_index_path).exists() or force:
        logging.info('Building index ...')
        index.reset()
        
        n = len(x)
        batch_size = index_batch_size or n
        build_time = time.time()
        for i in trange(0, n, batch_size, desc='ADD'):
            index.add(x[i:i + batch_size])
        index.commit()
        build_time = time.time() - build_time
        logging.info(f'Done in {build_time} s.')

        # save built index
        logging.info(f'Saving built index: {built_index_path}')
        with open(built_index_path, 'wb') as f:
            pickle.dump(index, f)

        build_metrics = pd.DataFrame({
            'build_time': build_time,
            'build_batch_size': index_batch_size,
            'index_density': index.density,
            'num_entries': index.db.nnz,
        }, index=[0])
        build_metrics.to_csv(build_metrics_path, index=False)

    else:
        logging.info(f'Reading prebuilt index from: {built_index_path}')
        with open(built_index_path, 'rb') as f:
            index = pickle.load(f)

        build_metrics = pd.read_csv(build_metrics_path)
    
    return index, build_metrics


def main(args):
    all_params = vars(args)

    train_params = all_params.pop('train_params') + ('index_type',)
    build_params = all_params.pop('build_params')
    query_params = all_params.pop('query_params')
    index_params = train_params + build_params + query_params

    train_params  = {k: v for k, v in all_params.items() if k     in train_params}
    build_params  = {k: v for k, v in all_params.items() if k     in build_params}
    query_params  = {k: v for k, v in all_params.items() if k     in query_params}
    common_params = {k: v for k, v in all_params.items() if k not in index_params}

    root_params = dict(**common_params, **train_params)
    ignore = common_params.keys() - {'dataset'}  # ignore all common params but 'dataset'
    exp_train = Experiment(root_params, root=args.exp_root, ignore=ignore)
    print(exp_train)

    # setup logging
    log_path = exp_train.path_to('log.txt')
    configure_logging(log_path)
    
    # load data in RAM
    dataset = get_dataset(args.dataset, args.data_root)
    
    logging.info(f'Loading data: {args.dataset}.hdf5')
    x = dataset['train'][:]
    q = dataset['test'][:10]
    n, d = x.shape
    true_neighbors = dataset['neighbors'][:10]
    _, lim = true_neighbors.shape

    # train index
    trained_index_path = exp_train.path_to('empty_trained_index.pickle')
    train_metrics_path = exp_train.path_to('train_metrics.csv')
    index, train_metrics = load_or_train_index(x, train_params, trained_index_path, train_metrics_path)

    # build index
    exp_build = Experiment(build_params, root=exp_train.path) if build_params else exp_train
    print(exp_build)
    built_index_path = exp_build.path_to('built_index.pickle')
    build_metrics_path = exp_build.path_to('build_metrics.csv')
    load_or_build_index(index, x, build_params, built_index_path, build_metrics_path, args.index_batch_size, args.force)

    # search and evaluate
    exp_search = Experiment(query_params, root=exp_build.path) if query_params else exp_build
    print(exp_search)

    search_metrics_path = exp_search.path_to('search_metrics.csv')
    if Path(search_metrics_path).exists() and not args.force:
        logging.info('Skipping run.')
        return

    batch_size = args.search_batch_size or len(q)
    logging.info('Searching and Evaluating index ...')
    search_time = time.time()
    nns = []
    search_cost = 0
    for i in trange(0, len(q), batch_size, desc='SEARCH'):
        _, nns_batch, cost = index.search(q[i:i + batch_size], k=lim, return_cost=True, **query_params)
        nns.append(nns_batch)
        search_cost += cost
    nns = np.vstack(nns)
    search_time = time.time() - search_time

    search_metrics = []
    for k in nice_logspace(lim):
        recalls = compute_recalls(true_neighbors[:, :k], nns[:, :k])
        search_metrics.append({
            'k': k,
            'recall@k.mean': recalls.mean(),
            'recall@k.std': recalls.std(),
        })
    
    search_metrics = pd.DataFrame(search_metrics)
    search_metrics['search_time'] = search_time
    search_metrics['search_cost'] = search_cost
    search_metrics.to_csv(search_metrics_path, index=False)

    logging.info(f'Done in {search_time} s.')


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Run Surrogate Text Representation Experiments',
                                     formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument('dataset', help='dataset from ann-benchmarks.com')

    parser.add_argument('--data-root', default='data/', help='where to store downloaded data')
    parser.add_argument('--exp-root', default='runs/', help='where to store results')

    parser.add_argument('--force', default=False, action='store_true', help='force index training')
    parser.add_argument('-b', '--index-batch-size', type=int, default=None, help='index data in batches with this size')
    parser.add_argument('-B', '--search-batch-size', type=int, default=None, help='search data in batches with this size')
    parser.add_argument('-t', '--search-timeout', type=int, default=1000, help='stop parameter search when search time (in seconds) is over this value')

    parser = surrogate.add_index_argparser(parser)
    args = parser.parse_args()
    main(args)