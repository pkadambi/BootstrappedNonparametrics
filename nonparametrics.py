from sklearn.neighbors import NearestNeighbors
import numpy as np
from scipy.spatial.distance import pdist, squareform
from scipy.sparse.csgraph import minimum_spanning_tree
from scipy.sparse import csr_matrix


def compute_delta_ijs(data, labels, n_classes):
    '''
    :param data:
    :param labels:
    :param n_classes:
    :return: a matrix of delta_ij where the delta_ij is
    '''
    n_samples = data.shape[0]
    delta_ij = np.zeros([n_classes, n_classes])

    eudist = csr_matrix(squareform(pdist(data)))
    mst = minimum_spanning_tree(eudist)
    mst = mst.toarray()
    edgelist = np.transpose(np.nonzero(mst))

    for i in range(n_classes):
        for j in range(i+1, n_classes):

            dij=0

            #aww yeah, brute forcing through the edges of the mst
            #TODO: can this be more efficient?
            for k in range(len(edgelist)):
                if labels[edgelist[k,0]]==i and labels[edgelist[k,1]]==j:
                    dij+=1

                elif labels[edgelist[k,0]]==j and labels[edgelist[k,1]]==i:
                    dij+=1

            dij = dij/ n_samples
            delta_ij[i, j] = dij
            delta_ij[j, i] = dij

    return delta_ij

def split_data_into_clusters(data, labels, cluster_memberships):

    clusters = np.unique(cluster_memberships)

    data_clustered = [data[cluster_memberships==cluster_ind, :] for cluster_ind in clusters]
    labels_clustered = [labels[cluster_memberships==cluster_ind] for cluster_ind in clusters]

    return data_clustered, labels_clustered


# def lowerbound_ber(d_ij, n_classes):
#     pass


def compute_neighbors(A, B, k=1, algorithm='auto'):
    '''
    For each sample in A, compute the nearest neighbor in B

    :inputs:
    A and B - both (n_samples x n_features)

    algorithm - look @ scipy NearestNeighbors nocumentation for this (ball_tre or kd_tree)
                dont use kd_tree if n_features>~20 or 30
    :return:
    a list of the closest points to each point in A and B

    '''
    nbrs = NearestNeighbors(n_neighbors=k + 1, algorithm=algorithm).fit(B)
    nns = nbrs.kneighbors(A)[1]
    nns = nns[:, 1]

    # exit()
    return nns



def dp_div(A, B, method='1nn'):
    '''
    Requires A and B to be the same number of dimensions

    *******
    WARNING!!!
    MST is very slow in this implementation, this is unlike matlab where they ahve comparable speeds
    Overall, MST takes ~25x LONGER!!

    Source of slowdown:
    conversion to and from CSR format adds ~10% of the time diff between 1nn and scipy mst function the remaining 90%

    *******
    '''

    data = np.vstack([A, B])
    N = A.shape[0]
    M = B.shape[0]
    labels = np.vstack([np.zeros([N, 1]), np.ones([M, 1])])

    if method == '1nn':
        nn_indices = compute_neighbors(data, data)
        # import pdb
        # pdb.set_trace()
        errors = np.sum(np.abs(labels[nn_indices] - labels))
        # print('Errors '+str(errors))
        Dp = 1 - ((M + N) / (2 * M * N)) * errors

    # TODO: improve speed for MST, requires a fast mst implementation
    # mst is at least 10x slower than knn approach
    elif method == 'mst':
        dense_eudist = squareform(pdist(data))
        eudist_csr = csr_matrix(dense_eudist)
        mst = minimum_spanning_tree(eudist_csr)
        mst = mst.toarray()
        edgelist = np.transpose(np.nonzero(mst))

        errors = np.sum(labels[edgelist[:, 0]] != labels[edgelist[:, 1]])

        Dp = 1 - ((M + N) / (2 * M * N)) * errors
    # Dp=1
    # errors=0
    Cij = errors

    return Dp, Cij







'''
Code below is for experiment and random functions
'''

def compute_entropy_for_clusters(data_clusters, teacher_model, temperature):
    import tqdm
    import torch
    import scipy.stats as stats
    import torch.nn.functional as F
    #loop through clusters

    teacher_model.eval()
    teacher_model.cuda()

    avg_entropy_per_cluster = np.zeros(len(data_clusters))
    per_sample_entropy_per_cluster = [np.zeros(len(d)) for d in data_clusters]

    for i, cluster in enumerate(tqdm.tqdm(data_clusters)):

        cluster_size = len(cluster)

        test_batch_size = 128

        k=0
        sample_entropies = np.zeros(cluster_size)

        while k<cluster_size:
            startind = k

            if k+test_batch_size<cluster_size:
                endind = k + test_batch_size
            else:
                endind = cluster_size

            inp_ = cluster[startind:endind]


            input = torch.Tensor(inp_).cuda()
            input = input.view(-1, 3, 32, 32) #reshape for correct input to network
            teacher_logits = teacher_model(input)
            teacher_soft_logits = F.softmax(teacher_logits/temperature, dim=1)
            teacher_soft_logits = teacher_soft_logits.detach().cpu().numpy()

            sample_entropies[startind:endind] = stats.entropy(teacher_soft_logits.T)
            k+=test_batch_size

        avg_entropy_per_cluster[i] = np.mean(sample_entropies, axis=0)
        per_sample_entropy_per_cluster[i] = sample_entropies

    return avg_entropy_per_cluster, per_sample_entropy_per_cluster

def calculate_alpha_hat(alpha, beta, n_classes, clusterwise_ber, examples_per_cluster):
    # calculate_alpha_hat(.1, .1, 10, bers, examples_per_cluster)
    w = [e/sum(examples_per_cluster) for e in examples_per_cluster]
    R = clusterwise_ber
    K = n_classes

    C = len(clusterwise_ber) # capital C is the number of clusters

    ahat_i = []
    for i in range(C):
        eq_subtr =  np.abs(R[i] * (K/(K -1)) - 1)
        eq_sum = np.sum([np.abs(R[c] * (K/ (K - 1)) - 1) * w[c] for c in range(C)])
        ahat_i.append(alpha + (beta/2) * (eq_sum - eq_subtr))

    # ahat_i = [alpha + (beta/2) * (np.sum([np.abs(R[c] * (K/ (K - 1)) - 1) * w[c] for c in range(C)]) -
    #           np.abs(R[i] * (K/(K -1)) - 1)) for i in range(C)]

    return ahat_i

def ber_from_delta_ij(delta_ij_matrix, n_classes):
    dij = delta_ij_matrix
    K = n_classes

    lb = ((K - 1) / K) * np.sqrt(
                1 - (1 - 2 *
                (K / (K - 1)) * np.sum([np.sum([dij[i, j] for j in range(i+1, K)]) for i in range(K-1)])))

    return lb


def calcualte_cluster_alpha_hat(clusters, labels, alpha, beta):
    for cluster, label in zip(clusters, labels):
        # 1. calculate delta ijs

        # 2. calculate ber lower bound (for each cluster)

        # 3. calculate

        pass
    pass


def pairwise_divergence_matrix(data, labels, n_classes):
    pairwise_hp_div_matrix = np.zeros([n_classes, n_classes])

    for i in range(n_classes):
        j = 0
        while j < n_classes:

            pass
# should be ~.4

def test_fashionmnist_clustering_and_ber():
    from data import get_dataset
    from preprocess import get_transform

    from sklearn.decomposition import PCA
    from sklearn.preprocessing import RobustScaler
    dataset = 'cifar10'

    train_data = get_dataset(name=dataset, split='train', transform=get_transform(name=dataset, augment=True))
    test_data = get_dataset(name=dataset, split='test', transform=get_transform(name=dataset, augment=False))

    from sklearn.cluster import KMeans

    data = np.vstack([tr[0].numpy().reshape(1, -1) for tr in train_data])
    labels = np.array([tr[1] for tr in train_data])

    # print('Started Scaling')
    # transformer = RobustScaler().fit(npdata)
    # data = transformer.transform(npdata)

    print('Started pca')
    pca = PCA(n_components=256).fit(data)
    data_reduc = pca.transform(data)

    print('Explained Variance: %.2f' % np.sum(pca.explained_variance_ratio_))


    data_reduc = pca.transform(data)
    from sklearn.mixture import GaussianMixture
    gmm = GaussianMixture(n_components=64)
    gmm.fit(data_reduc)
    cluster_labels = gmm.predict(data_reduc)
    # cluster_labels = np.loadtxt('./clifar10_clusters_pca256_gmm64.txt')
    data_clustered, labels_clustered = split_data_into_clusters(data_reduc, labels, cluster_memberships=cluster_labels )

    print('Computing Delta_ij')
    dijs=[compute_delta_ijs(data,labels, n_classes=10) for data, lables in zip(data_clustered, labels_clustered)]

    import pickle as pkl
    pkl.dump({'dijs': dijs}, open('./cifar10_pca256_gmm64_dij_matrix','wb'))

    print('Computing BER')
    bers = [ber_from_delta_ij(dij, n_classes=10) for dij in dijs]
    examples_per_cluster = [len(d) for d in data_clustered]

    print('Computing alpha hat')
    alpha_hat = calculate_alpha_hat(.2, .05, 10, bers, examples_per_cluster)
    print(alpha_hat)
    print()

# dpdivvalue=dp_div(a,b,method='mst')
def time_difference_tester():
    import time
    start = time.time()
    n_dims = 8

    for i in range(25):
        a = np.random.rand(1000, n_dims)
        b = np.hstack([np.random.rand(1000, 1) + .5, np.random.rand(1000, n_dims - 1)])
        dp_div(a, b, method='1nn')
    end = time.time()
    print('1nn elapsed time:\t', end - start)

    for i in range(25):
        a = np.random.rand(1000, n_dims)
        b = np.hstack([np.random.rand(1000, 1) + .5, np.random.rand(1000, n_dims - 1)])
        dp_div(a, b, method='mst')
    end2 = time.time()
    print('MST elapsed time:\t', end2 - end)


def test_dp_equals_onehalf():
    '''

    true dpdiv for this test is 0.5 (when ndims=8)

    the finite sample biased estiamte should be ~0.4
    :return:
    '''
    n_dims = 8

    a = np.random.randn(2500, n_dims)
    b = np.hstack([np.random.randn(2500, 1) + 1, np.random.randn(2500, 1) + 1, np.random.randn(2500, n_dims - 2)])

    print('Point Estimates')
    print(dp_div(a, b, method='1nn'))
    print(dp_div(a, b, method='mst'))

    print('Asymp Estimate')
    print(asym)

# test_dp_eqals_onehalf()
# test_fashionmnist_clustering_and_ber()


# print(dp_div(a,b,method='1nn'))
def tester():
    n_dims = 8
    methods = ['kd_tree', 'ball_tree', 'brute']
    print('N_DIMS = ' + str(n_dims))
    import time
    for method in methods:
        dp = []
        start = time.time()
        for k in range(100):
            a = np.random.rand(10, n_dims)
            b = np.hstack([np.random.rand(10, 1) + .5, np.random.rand(10, n_dims - 1)])
            dp.append(dp_div(a, b))
        end = time.time()
        print('For Method: ' + method + '\tAvg DpDiv is : ' + str(np.mean(dp)) + '\t Elapsed: ' + str(end - start))

    # compute_neighbors(a,b)
    print(a.shape)
    print(b.shape)
    print(dp_div(a, b))

    a = np.random.rand(1000, 8)
    b = np.hstack([np.random.rand(1000, 1) + .5, np.random.rand(1000, 7)])
    print(dp_div(a, b))
