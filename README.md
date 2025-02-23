Surrogate Text Encoders for Real Vectors
---

## Installation

```sh
pip install git+https://github.com/fabiocarrara/str-encoders
```

## Usage Example
```python
import surrogate

# load data in a numpy NxD matrix
n = 100
d = 256
x = np.random.rand(n, d)

# create encoder
enc = surrogate.IVFTopKSQ(
    d,  # input dimensionality
    n_coarse_centroids=10,  # n. of voronoi partitions
    keep=0.75,  # percentage of components to keep
)

# train encoder
enc.train(x)

# save trained encoder
surrogate.save_index(enc, 'my_index.pkl')

# load trained encoder
enc = surrogate.load_index('my_index.pkl')

# encode vectors (with inverted=False, x_enc is a NxV sparse matrix, V = vocab size)
x_enc = enc.encode(x, inverted=False)

# generate documents (x_docs is a generator of strings)
x_docs = surrogate.generate_documents(x_enc)

with open('docs.txt', 'w') as f:
    for doc in x_docs:
        f.write(doc)
        f.write('\n')

# -------------------------------

# query encoding
q = np.random.rand(1, d)

# set how many voronoi partitions to access at query time
enc.nprobe = 15

# encode query (use query=True)
q_enc = enc.encode(q, inverted=False, query=True)

# generate surrogate document
q_docs = surrogate.generate_documents(q_enc)

# print the document
print(next(q_docs))
```
