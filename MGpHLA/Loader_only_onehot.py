import os
from torch_geometric.data import InMemoryDataset, DataLoader, Batch
from torch_geometric import data as DATA
from torch_geometric.nn import GCNConv, GCN2Conv, GATConv, global_max_pool as gmp, global_add_pool as gap, \
    global_mean_pool as gep, global_sort_pool
import torch
import numpy as np
import re


import math
from sklearn import metrics
from sklearn import preprocessing
import matplotlib.pyplot as plt
import pandas as pd
import re
import time
import datetime
import random
import torch.nn as nn
from data_transform import transform_data, CATHDataset
seed = 0
random.seed(seed)
np.random.seed(seed)
torch.manual_seed(seed)
torch.cuda.manual_seed(seed)
torch.cuda.manual_seed_all(seed)
torch.backends.cudnn.benchmark = False
torch.backends.cudnn.deterministic = True

from scipy import interp
import warnings
warnings.filterwarnings("ignore")

#from model2 import make_data,MyDataSet
from collections import Counter
from functools import reduce
from tqdm import tqdm, trange
from copy import deepcopy
from sklearn.metrics import confusion_matrix
from sklearn.metrics import roc_auc_score, auc
from sklearn.metrics import precision_recall_fscore_support
from sklearn.metrics import precision_recall_curve
from sklearn.metrics import classification_report
from sklearn.utils import class_weight

import traceback
import pandas as pd
import numpy as np
import networkx as nx
import sys
import os
import random

import json, pickle
from collections import OrderedDict
from rdkit import Chem
from rdkit.Chem import MolFromSmiles
from tqdm import tqdm
from utils import *

sys.path.append('/')
from utils import hla_key_and_setTrans,hla_key_and_setTrans_2,hla_key_full_sequence
#from feature_extraction_contact import sequence_to_graph,batch_seq_feature
from feature_extraction_contact_only_onehot import sequence_to_graph,batch_seq_feature_only_onehot

#还需要引入数据处理文件中的函数(得到hla_dict等)
#还需要引入特征提取文件中提取序列特征的函数


TRAIN_BATCH_SIZE = 512
TEST_BATCH_SIZE = 512
max_pro_seq_len = 348

vocab = np.load('/home1/layomi/项目代码/MMGHLA_CT/MGpHLA/model/vocab_dict.npy', allow_pickle = True).item()
vocab_size = len(vocab)

def read_blosum(path):
    '''
    Read the blosum matrix from the file blosum50.txt
    Args:
        1. path: path to the file blosum50.txt
    Return values:
        1. The blosum50 matrix
    '''
    f = open(path,"r")
    blosum = []
    for line in f:
        blosum.append([(float(i))/10 for i in re.split("\t",line)])
        #The values are rescaled by a factor of 1/10 to facilitate training
    f.close()
    return blosum

aa={"A":0,"R":1,"N":2,"D":3,"C":4,"Q":5,"E":6,"G":7,"H":8,"I":9,"L":10,"K":11,"M":12,"F":13,"P":14,"S":15,"T":16,"W":17,"Y":18,"V":19}     
#Load the blosum matrix for encoding
path_blosum = '../data/blosum50.txt'
blosum_matrix = read_blosum(path_blosum)


def P_or_N(list_entry):
    peptide_seq=[]
    p_entries=[]
    n_entries=[]
    for i in range(len(list_entry)):
        peptide_seq.append(list_entry[i][1])
        if float(list_entry[i][2])==1:
            p_entries.append(list_entry[i])
        if float(list_entry[i][2])==0:
            n_entries.append(list_entry[i])
    peptide_type=list(set(peptide_seq))
    return p_entries,n_entries,peptide_type

def train_predict_div(train_file,vaild_file,dataset_structure,seed):    
    
    common_hla_file='/home1/layomi/项目代码/MMGHLA_CT/data/contact/common_hla_sequence.csv'
    train_entries,train_hla_keys,train_hla_dict,hla_dict=hla_key_and_setTrans(common_hla_file,train_file)
    vaild_entries,vaild_hla_keys,vaild_hla_dict,hla_dict=hla_key_and_setTrans(common_hla_file,vaild_file)
      
    train_p_entries,train_n_entries,train_peptide_type=P_or_N(train_entries)
    vaild_p_entries,vaild_n_entries,vaild_peptide_type=P_or_N(vaild_entries)
    
    random.seed(seed)

    
    random.shuffle(train_entries)
    #random.shuffle(train_p_entries)
    #random.shuffle(train_n_entries)

    random.shuffle(vaild_entries)
    #random.shuffle(vaild_p_entries)
    #random.shuffle(vaild_n_entries)


    hla_full_sequence_dict=dict()
    full_seq_dict=json.load(open('/home1/layomi/项目代码/MMGHLA_CT/data/contact/common_hla_full_sequence.txt'), object_pairs_hook=OrderedDict)
    for key,value in full_seq_dict.items():
        key=int(key)
        hla_full_sequence_dict[key]=value
    
    # 构建接触图
    process_dir = os.path.join('/home/layomi/drive1/项目代码/MMGHLA', 'data/pre_process')
    hla_distance_dir = os.path.join(process_dir, 'contact/distance_map')  # numpy .npy file   这里给出接触图的路径
    # create hla graph
    hla_graph = dict()    
    for i in tqdm(range(len(hla_dict))):
        key = 1000+i
        seq=hla_full_sequence_dict[key]
        g_h = sequence_to_graph(key, seq, hla_distance_dir)
        hla_graph[key] = g_h
           

    #为类别图结点做初始化
    all_hla_graph=[]
    
    for key in sorted(hla_graph.keys()):
        hla_size,hla_features,hla_edge_index,hla_edges_weights=hla_graph[key]
        GCNData_hla = DATA.Data(x=torch.Tensor(hla_features),
                                edge_index=torch.LongTensor(hla_edge_index).transpose(1, 0),
                                edge_weight=torch.FloatTensor(hla_edges_weights))
        GCNData_hla.__setitem__('hla_size', torch.LongTensor([hla_size]))
        all_hla_graph.append(GCNData_hla)
        
     
    #这一段的意义是给训练测试数据集中每个hla配备了接触图，所以，我必须把3-D分子图也输入进入，给每个hla配备上
    train_hlas,train_peptides,train_Y=np.asarray(train_entries)[:,0],np.asarray(train_entries)[:,1],np.asarray(train_entries)[:,2]
    train_dataset=HPIDataset(root='data', dataset=train_file + '_' + 'train', xd=train_hlas, peptide_key=train_peptides,
                               y=train_Y.astype(float), hla_contact_graph=hla_graph,hla_3d_graph=dataset_structure)
    vaild_hlas,vaild_peptides,vaild_Y=np.asarray(vaild_entries)[:,0],np.asarray(vaild_entries)[:,1],np.asarray(vaild_entries)[:,2]
    vaild_dataset=HPIDataset(root='data', dataset=vaild_file + '_' + 'dev', xd=vaild_hlas, peptide_key=vaild_peptides,
                               y=vaild_Y.astype(float), hla_contact_graph=hla_graph,hla_3d_graph=dataset_structure)

    return train_dataset, vaild_dataset,all_hla_graph


def train_predict_div(train_file,vaild_file,dataset_structure,seed):    
    
    common_hla_file='/home1/layomi/项目代码/MMGHLA_CT/data/contact/common_hla_sequence.csv'
    train_entries,train_hla_keys,train_hla_dict,hla_dict=hla_key_and_setTrans(common_hla_file,train_file)
    vaild_entries,vaild_hla_keys,vaild_hla_dict,hla_dict=hla_key_and_setTrans(common_hla_file,vaild_file)
      
    train_p_entries,train_n_entries,train_peptide_type=P_or_N(train_entries)
    vaild_p_entries,vaild_n_entries,vaild_peptide_type=P_or_N(vaild_entries)
    
    random.seed(seed)

    
    random.shuffle(train_entries)
    #random.shuffle(train_p_entries)
    #random.shuffle(train_n_entries)

    random.shuffle(vaild_entries)
    #random.shuffle(vaild_p_entries)
    #random.shuffle(vaild_n_entries)


    hla_full_sequence_dict=dict()
    full_seq_dict=json.load(open('/home1/layomi/项目代码/MMGHLA_CT/data/contact/common_hla_full_sequence.txt'), object_pairs_hook=OrderedDict)
    for key,value in full_seq_dict.items():
        key=int(key)
        hla_full_sequence_dict[key]=value
    
    # 构建接触图
    process_dir = os.path.join('/home/layomi/drive1/项目代码/MMGHLA', 'data/pre_process')
    hla_distance_dir = os.path.join(process_dir, 'contact/distance_map')  # numpy .npy file   这里给出接触图的路径
    # create hla graph
    hla_graph = dict()    
    for i in tqdm(range(len(hla_dict))):
        key = 1000+i
        seq=hla_full_sequence_dict[key]
        g_h = sequence_to_graph(key, seq, hla_distance_dir)
        hla_graph[key] = g_h
           

    #为类别图结点做初始化
    all_hla_graph=[]
    
    for key in sorted(hla_graph.keys()):
        hla_size,hla_features,hla_edge_index,hla_edges_weights=hla_graph[key]
        GCNData_hla = DATA.Data(x=torch.Tensor(hla_features),
                                edge_index=torch.LongTensor(hla_edge_index).transpose(1, 0),
                                edge_weight=torch.FloatTensor(hla_edges_weights))
        GCNData_hla.__setitem__('hla_size', torch.LongTensor([hla_size]))
        all_hla_graph.append(GCNData_hla)
        
     
    #这一段的意义是给训练测试数据集中每个hla配备了接触图，所以，我必须把3-D分子图也输入进入，给每个hla配备上
    train_hlas,train_peptides,train_Y=np.asarray(train_entries)[:,0],np.asarray(train_entries)[:,1],np.asarray(train_entries)[:,2]
    train_dataset=HPIDataset(root='data', dataset=train_file + '_' + 'train', xd=train_hlas, peptide_key=train_peptides,
                               y=train_Y.astype(float), hla_contact_graph=hla_graph,hla_3d_graph=dataset_structure)
    vaild_hlas,vaild_peptides,vaild_Y=np.asarray(vaild_entries)[:,0],np.asarray(vaild_entries)[:,1],np.asarray(vaild_entries)[:,2]
    vaild_dataset=HPIDataset(root='data', dataset=vaild_file + '_' + 'dev', xd=vaild_hlas, peptide_key=vaild_peptides,
                               y=vaild_Y.astype(float), hla_contact_graph=hla_graph,hla_3d_graph=dataset_structure)

    return train_dataset, vaild_dataset,all_hla_graph


def train_predict_div_pep(train_file,vaild_file,dataset_structure,seed):    #数据集应该为未划分训练集测试集验证集的全数据集
    
    common_hla_file='/home1/layomi/项目代码/MMGHLA_CT/data/contact/common_hla_sequence.csv'
    train_entries,train_hla_keys,train_hla_dict,hla_dict=hla_key_and_setTrans(common_hla_file,train_file)
    vaild_entries,vaild_hla_keys,vaild_hla_dict,hla_dict=hla_key_and_setTrans(common_hla_file,vaild_file)
    
      
    train_p_entries,train_n_entries,train_peptide_type=P_or_N(train_entries)
    vaild_p_entries,vaild_n_entries,vaild_peptide_type=P_or_N(vaild_entries)
    
    random.seed(seed)
    random.shuffle(train_entries)
    #random.shuffle(train_p_entries)
    #random.shuffle(train_n_entries)

    random.shuffle(vaild_entries)
    #random.shuffle(vaild_p_entries)
    #random.shuffle(vaild_n_entries)
    
    


    hla_full_sequence_dict=dict()
    full_seq_dict=json.load(open('/home1/layomi/项目代码/MMGHLA_CT/data/contact/common_hla_key_full_sequence_new.txt'), object_pairs_hook=OrderedDict)
    for key,value in full_seq_dict.items():
        key=int(key)
        hla_full_sequence_dict[key]=value
    
    # 构建接触图/home/layomi/drive1/项目代/home/layomi/drive1/项目代码/MMGHLA_Classification_Topography码/MMGHLA_Classification_Topography
    process_dir = os.path.join('/home1/layomi/项目代码/MMGHLA_CT', 'data/pre_process')
    hla_distance_dir = os.path.join(process_dir, 'contact/distance_map')  # numpy .npy file   这里给出接触图的路径
    # create hla graph/home/layomi/drive1/项目代码/MMGHLA_Classification_Topography
    hla_graph = dict()    
    for i in tqdm(range(len(hla_dict))):
        key = i
        seq=hla_full_sequence_dict[key]
        g_h = sequence_to_graph(key, seq, hla_distance_dir)
        hla_graph[key] = g_h
           
    train_hlas,train_peptides,train_Y=np.asarray(train_entries)[:,0],np.asarray(train_entries)[:,1],np.asarray(train_entries)[:,2]
    vaild_hlas,vaild_peptides,vaild_Y=np.asarray(vaild_entries)[:,0],np.asarray(vaild_entries)[:,1],np.asarray(vaild_entries)[:,2]
    
    train_pep_feature=batch_seq_feature(train_peptides,15,33)
    vaild_pep_feature=batch_seq_feature(vaild_peptides,15,33)
    
        
    
    #这一段的意义是给训练测试数据集中每个hla配备了接触图，所以，我必须把3-D分子图也输入进入，给每个hla配备上
    
    train_dataset=HPIDataset_peps(root='data', dataset=train_file + '_' + 'train', xd=train_hlas, peptide_key=train_peptides,
                               y=train_Y.astype(float), hla_contact_graph=hla_graph,hla_3d_graph=dataset_structure,peps_feature=train_pep_feature)
    
    vaild_dataset=HPIDataset_peps(root='data', dataset=vaild_file + '_' + 'dev', xd=vaild_hlas, peptide_key=vaild_peptides,
                               y=vaild_Y.astype(float), hla_contact_graph=hla_graph,hla_3d_graph=dataset_structure,peps_feature=vaild_pep_feature)
    
    

    return train_dataset, vaild_dataset


def train_predict_div_pep_new(train_file,vaild_file,dataset_structure,seed):    #数据集应该为未划分训练集测试集验证集的全数据集
    
    common_hla_file='/home1/layomi/项目代码/MMGHLA_CT/data/contact/common_hla_sequence.csv'
    train_entries,train_hla_keys,train_hla_dict,hla_dict=hla_key_and_setTrans(common_hla_file,train_file)
    vaild_entries,vaild_hla_keys,vaild_hla_dict,hla_dict=hla_key_and_setTrans(common_hla_file,vaild_file)
    
      
    train_p_entries,train_n_entries,train_peptide_type=P_or_N(train_entries)
    vaild_p_entries,vaild_n_entries,vaild_peptide_type=P_or_N(vaild_entries)
    
    random.seed(seed)
    random.shuffle(train_entries)
    #random.shuffle(train_p_entries)
    #random.shuffle(train_n_entries)

    random.shuffle(vaild_entries)
    #random.shuffle(vaild_p_entries)
    #random.shuffle(vaild_n_entries)
    
    


    hla_full_sequence_dict=dict()
    full_seq_dict=json.load(open('/home1/layomi/项目代码/MMGHLA_CT/data/contact/common_hla_key_full_sequence_new.txt'), object_pairs_hook=OrderedDict)
    for key,value in full_seq_dict.items():
        key=int(key)
        hla_full_sequence_dict[key]=value
    
    # 构建接触图/home/layomi/drive1/项目代/home/layomi/drive1/项目代码/MMGHLA_Classification_Topography码/MMGHLA_Classification_Topography
    process_dir = os.path.join('/home1/layomi/项目代码/MMGHLA_CT', 'data/pre_process')
    hla_distance_dir = os.path.join(process_dir, 'contact/distance_map')  # numpy .npy file   这里给出接触图的路径
    # create hla graph/home/layomi/drive1/项目代码/MMGHLA_Classification_Topography
    hla_graph = dict()    
    all_hla_len=[]
    for i in tqdm(range(len(hla_dict))):
        key = i
        seq=hla_full_sequence_dict[key]
        g_h = sequence_to_graph(key, seq, hla_distance_dir)
        hla_graph[key] = g_h
        all_hla_length=len(seq)
        all_hla_len.append(all_hla_length)
           
    train_hlas,train_peptides,train_Y=np.asarray(train_entries)[:,0],np.asarray(train_entries)[:,1],np.asarray(train_entries)[:,2]
    vaild_hlas,vaild_peptides,vaild_Y=np.asarray(vaild_entries)[:,0],np.asarray(vaild_entries)[:,1],np.asarray(vaild_entries)[:,2]
    
    train_pep_feature=batch_seq_feature(train_peptides,15,33)
    vaild_pep_feature=batch_seq_feature(vaild_peptides,15,33)
    
        
    
    #这一段的意义是给训练测试数据集中每个hla配备了接触图，所以，我必须把3-D分子图也输入进入，给每个hla配备上
    
    train_dataset=HPIDataset_peps_new(root='data', dataset=train_file + '_' + 'train', xd=train_hlas, peptide_key=train_peptides,
                               y=train_Y.astype(float), hla_contact_graph=hla_graph,hla_3d_graph=dataset_structure,peps_feature=train_pep_feature,all_hla_len=all_hla_len)
    
    vaild_dataset=HPIDataset_peps_new(root='data', dataset=vaild_file + '_' + 'dev', xd=vaild_hlas, peptide_key=vaild_peptides,
                               y=vaild_Y.astype(float), hla_contact_graph=hla_graph,hla_3d_graph=dataset_structure,peps_feature=vaild_pep_feature,all_hla_len=all_hla_len)
    
    

    return train_dataset, vaild_dataset


def train_predict_div_pep_new_blousm(train_file,vaild_file,dataset_structure,seed):    #数据集应该为未划分训练集测试集验证集的全数据集
    
    common_hla_file='/home1/layomi/项目代码/MMGHLA_CT/data/contact/common_hla_sequence.csv'
    train_entries,train_hla_keys,train_hla_dict,hla_dict=hla_key_and_setTrans(common_hla_file,train_file)
    vaild_entries,vaild_hla_keys,vaild_hla_dict,hla_dict=hla_key_and_setTrans(common_hla_file,vaild_file)
    
      
    train_p_entries,train_n_entries,train_peptide_type=P_or_N(train_entries)
    vaild_p_entries,vaild_n_entries,vaild_peptide_type=P_or_N(vaild_entries)
    
    random.seed(seed)
    random.shuffle(train_entries)
    #random.shuffle(train_p_entries)
    #random.shuffle(train_n_entries)

    random.shuffle(vaild_entries)
    #random.shuffle(vaild_p_entries)
    #random.shuffle(vaild_n_entries)
    
    


    hla_full_sequence_dict=dict()
    full_seq_dict=json.load(open('/home1/layomi/项目代码/MMGHLA_CT/data/contact/common_hla_key_full_sequence_new.txt'), object_pairs_hook=OrderedDict)
    for key,value in full_seq_dict.items():
        key=int(key)
        hla_full_sequence_dict[key]=value
    
    # 构建接触图/home/layomi/drive1/项目代/home/layomi/drive1/项目代码/MMGHLA_Classification_Topography码/MMGHLA_Classification_Topography
    process_dir = os.path.join('/home1/layomi/项目代码/MMGHLA_CT', 'data/pre_process')
    hla_distance_dir = os.path.join(process_dir, 'contact/distance_map')  # numpy .npy file   这里给出接触图的路径
    # create hla graph/home/layomi/drive1/项目代码/MMGHLA_Classification_Topography
    hla_graph = dict()    
    all_hla_len=[]
    for i in tqdm(range(len(hla_dict))):
        key = i
        seq=hla_full_sequence_dict[key]
        g_h = sequence_to_graph(key, seq, hla_distance_dir)
        hla_graph[key] = g_h
        all_hla_length=len(seq)
        all_hla_len.append(all_hla_length)
           
    train_hlas,train_peptides,train_Y=np.asarray(train_entries)[:,0],np.asarray(train_entries)[:,1],np.asarray(train_entries)[:,2]
    vaild_hlas,vaild_peptides,vaild_Y=np.asarray(vaild_entries)[:,0],np.asarray(vaild_entries)[:,1],np.asarray(vaild_entries)[:,2]
    
    train_pep_feature=batch_seq_feature(train_peptides,15,33)
    vaild_pep_feature=batch_seq_feature(vaild_peptides,15,33)
    
def train_predict_div_pep_new_blousm_onlyonehot_weight(train_file,vaild_file,dataset_structure,seed):    #数据集应该为未划分训练集测试集验证集的全数据集
    
    common_hla_file='/home1/layomi/项目代码/MMGHLA_CT/data/contact/common_hla_sequence.csv'
    train_entries,train_hla_keys,train_hla_dict,hla_dict=hla_key_and_setTrans(common_hla_file,train_file)
    vaild_entries,vaild_hla_keys,vaild_hla_dict,hla_dict=hla_key_and_setTrans(common_hla_file,vaild_file)
    
      
    train_p_entries,train_n_entries,train_peptide_type=P_or_N(train_entries)
    vaild_p_entries,vaild_n_entries,vaild_peptide_type=P_or_N(vaild_entries)
    
    random.seed(seed)
    random.shuffle(train_entries)
    #random.shuffle(train_p_entries)
    #random.shuffle(train_n_entries)

    random.shuffle(vaild_entries)
    #random.shuffle(vaild_p_entries)
    #random.shuffle(vaild_n_entries)
    
    


    hla_full_sequence_dict=dict()
    full_seq_dict=json.load(open('/home1/layomi/项目代码/MMGHLA_CT_blousm/data/contact/common_hla_key_full_sequence_new.txt'), object_pairs_hook=OrderedDict)
    for key,value in full_seq_dict.items():
        key=int(key)
        hla_full_sequence_dict[key]=value
    
    # 构建接触图/home/layomi/drive1/项目代/home/layomi/drive1/项目代码/MMGHLA_Classification_Topography码/MMGHLA_Classification_Topography
    process_dir = os.path.join('/home1/layomi/项目代码/MMGHLA_CT_blousm', 'data/pre_process')
    hla_distance_dir = os.path.join(process_dir, 'contact/distance_map')  # numpy .npy file   这里给出接触图的路径
    # create hla graph/home/layomi/drive1/项目代码/MMGHLA_Classification_Topography
    hla_graph = dict()    
    all_hla_len=[]
    for i in tqdm(range(len(hla_dict))):
        key = i
        seq=hla_full_sequence_dict[key]
        g_h = sequence_to_graph(key, seq, hla_distance_dir)
        hla_graph[key] = g_h
        all_hla_length=len(seq)-24
        all_hla_len.append(all_hla_length)
           
    train_hlas,train_peptides,train_Y=np.asarray(train_entries)[:,0],np.asarray(train_entries)[:,1],np.asarray(train_entries)[:,2]
    vaild_hlas,vaild_peptides,vaild_Y=np.asarray(vaild_entries)[:,0],np.asarray(vaild_entries)[:,1],np.asarray(vaild_entries)[:,2]
    
    train_pep_feature=batch_seq_feature_only_onehot(train_peptides,15,21)
    vaild_pep_feature=batch_seq_feature_only_onehot(vaild_peptides,15,21)
    
        
    
    #这一段的意义是给训练测试数据集中每个hla配备了接触图，所以，我必须把3-D分子图也输入进入，给每个hla配备上
    
    train_dataset=HPIDataset_peps_new_only_onehot(root='data', dataset=train_file + '_' + 'train', xd=train_hlas, peptide_key=train_peptides,
                               y=train_Y.astype(float), hla_contact_graph=hla_graph,hla_3d_graph=dataset_structure,peps_feature=train_pep_feature,all_hla_len=all_hla_len)
    
    vaild_dataset=HPIDataset_peps_new_only_onehot(root='data', dataset=vaild_file + '_' + 'dev', xd=vaild_hlas, peptide_key=vaild_peptides,
                               y=vaild_Y.astype(float), hla_contact_graph=hla_graph,hla_3d_graph=dataset_structure,peps_feature=vaild_pep_feature,all_hla_len=all_hla_len)
    
    

    return train_dataset, vaild_dataset

class HPIDataset_peps_new_only_onehot(InMemoryDataset):
    def __init__(self,root='../data',xh=None, y=None, transform=None,
                 pre_transform=None, hla_contact_graph=None, hla_blousm=None,peptide_key=None,hla_3d_graph=None,peps_feature=None,all_hla_len=None):
        super(HPIDataset_peps_new_only_onehot, self).__init__(root, transform, pre_transform)
 
        self.hla=xh
        self.peptide_key=peptide_key    #peptide的key就是它本身
        self.y=y
        self.hla_contact_graph=hla_contact_graph
        self.hla_3d_graph=hla_3d_graph
        self.hla_blousm=hla_blousm
        self.peps_feature=peps_feature
        self.all_hla_len=all_hla_len
        self.process(xh,peptide_key,y,hla_contact_graph,hla_3d_graph,all_hla_len,peps_feature)

    @property
    def raw_file_names(self):
        pass
        # return ['some_file_1', 'some_file_2', ...]

    @property
    def processed_file_names(self):
        return [self.dataset + '_data_hla.pt', self.dataset + '_data_pep.pt']

    def download(self):
        # Download to `self.raw_dir`.
        pass

    def _download(self):
        pass

    def _process(self):
        if not os.path.exists(self.processed_dir):
            os.makedirs(self.processed_dir)

    def process(self, xd, peptide_key, y, hla_contact_graph,hla_3d_graph,all_hla_len,peps_feature):
        
        assert (len(xd) == len(peptide_key) and len(xd) == len(y)), 'The three lists must have the same length!'
        data_list_hlacontact = []
        data_list_hla3D=[]
        data_list_pep = []
        data_list_pep_feature=[]
        data_len = len(xd)
        #hla_key=[]
        for i in tqdm(range(data_len)):
            hla = int(xd[i])
            pep_key = peptide_key[i]
            pep_feature=peps_feature[i]
            '''
            pep_feature=torch.tensor(pep_feature)
            pep_feature=pep_feature*3
            '''
            labels = y[i]
            #contact_graph_data
            hla_size,hla_contact_features,hla_edge_index,hla_edges_weights=hla_contact_graph[hla]
            hla_features=torch.tensor(hla_contact_features,dtype=torch.float32)
            #hla_features=torch.cat((torch.Tensor(hla_contact_features),torch.Tensor(hla_blousm[hla])),axis=-1)
            residue_indices = [7,9,24,45,59,62,63,66,67,69,70,73,74,76,77,80,81,84,95,97,99,114,116,118,143,147,150,
                       152,156,158,159,163,167,171]
            residue_indices = [i - 1 for i in residue_indices]
            
            valid_indices = [i for i in residue_indices if i < hla_features.size(0)]
            #hla_features[valid_indices] = hla_features[valid_indices] * 5.0  # 将这些节点特征放大2倍
            hla_features[valid_indices] = hla_features[valid_indices] * 3.0  # 将这些节点特征放大2倍
            #hla_features[valid_indices] = hla_features[valid_indices] * 2.0  # 将这些节点特征放大2倍
            ContactData_hla = DATA.Data(x=torch.Tensor(hla_features),
                                    edge_index=torch.LongTensor(hla_edge_index).transpose(1, 0),
                                    edge_weight=torch.FloatTensor(hla_edges_weights),hla_len=all_hla_len[hla],hla_key=hla,
                                    y=torch.FloatTensor([labels]))
            ContactData_hla.__setitem__('hla_size', torch.LongTensor([hla_size]))
            
            #3-d-mol-data
            ThreeD_hla=hla_3d_graph[hla]  #ThreeD_hla type=orch_geometric.data.Data
            '''
            Three_D_hla_x=torch.tensor(ThreeD_hla.x)
            Three_D_hla_x[valid_indices]=Three_D_hla_x[valid_indices]*3
            ThreeD_hla.x=Three_D_hla_x
            '''
            #ThreeD_hla[valid_indices]=ThreeD_hla[valid_indices]*3.0
            
            #Data_pep=DATA.Data(x=pep_feature,sequence=peptide_key,pep_len=len(peptide_key))
            Data_pep = {
                        'x': pep_feature,
                        'sequence': peptide_key,
                        'length': len(pep_feature)
                    }
            
            data_list_hlacontact.append(ContactData_hla)
            data_list_hla3D.append(ThreeD_hla)
            
            data_list_pep.append(Data_pep)
            #data_list_pep_feature.append(pep_feature)
            #hla_key.append(hla)

           
        self.data_hla_contact = data_list_hlacontact
        self.data_hla_3D=data_list_hla3D
        self.data_pep=data_list_pep
        #self.peps_feature=data_list_pep_feature
        #self.data_hla_key=hla_key
        
        
    def __len__(self):
        return len(self.y)

    def __getitem__(self, idx):
        # return GNNData_mol, GNNData_pro
        return self.data_hla_contact[idx], self.data_hla_3D[idx],self.data_pep[idx]
def train_predict_test_div(train_file,vaild_file,test_file,dataset_structure,seed):    #数据集应该为未划分训练集测试集验证集的全数据集
    
    common_hla_file='/home1/layomi/项目代码/MMGHLA_CT/data/contact/common_hla_sequence.csv'
    train_entries,train_hla_keys,train_hla_dict,hla_dict=hla_key_and_setTrans(common_hla_file,train_file)
    vaild_entries,vaild_hla_keys,vaild_hla_dict,hla_dict=hla_key_and_setTrans(common_hla_file,vaild_file)
    test_entries,test_hla_keys,test_hla_dict,hla_dict=hla_key_and_setTrans_2(common_hla_file,test_file)
      
    train_p_entries,train_n_entries,train_peptide_type=P_or_N(train_entries)
    vaild_p_entries,vaild_n_entries,vaild_peptide_type=P_or_N(vaild_entries)
    test_p_entries,test_n_entries,test_peptide_type=P_or_N(test_entries)
    
    random.seed(seed)
    random.shuffle(train_entries)
    #random.shuffle(train_p_entries)
    #random.shuffle(train_n_entries)

    random.shuffle(vaild_entries)
    #random.shuffle(vaild_p_entries)
    #random.shuffle(vaild_n_entries)
    
    random.shuffle(test_entries)
    #random.shuffle(test_p_entries)
    #random.shuffle(test_n_entries)


    hla_full_sequence_dict=dict()
    full_seq_dict=json.load(open('/home1/layomi/项目代码/MMGHLA_CT/data/contact/common_hla_key_full_sequence.txt'), object_pairs_hook=OrderedDict)
    for key,value in full_seq_dict.items():
        key=int(key)
        hla_full_sequence_dict[key]=value
    
    # 构建接触图
    process_dir = os.path.join('/home1/layomi/项目代码/MMGHLA_CT', 'data/pre_process')
    hla_distance_dir = os.path.join(process_dir, 'contact/distance_map')  # numpy .npy file   这里给出接触图的路径
    # create hla graph
    hla_graph = dict()    
    for i in tqdm(range(len(hla_dict))):
        key = 1000+i
        seq=hla_full_sequence_dict[key]
        g_h = sequence_to_graph(key, seq, hla_distance_dir)
        hla_graph[key] = g_h
           
  
    all_hla_graph=[]
    
    for key in sorted(hla_graph.keys()):
        hla_size,hla_features,hla_edge_index,hla_edges_weights=hla_graph[key]
        GCNData_hla = DATA.Data(x=torch.Tensor(hla_features),
                                edge_index=torch.LongTensor(hla_edge_index).transpose(1, 0),
                                edge_weight=torch.FloatTensor(hla_edges_weights))
        GCNData_hla.__setitem__('hla_size', torch.LongTensor([hla_size]))
        all_hla_graph.append(GCNData_hla)
        
    
    #这一段的意义是给训练测试数据集中每个hla配备了接触图，所以，我必须把3-D分子图也输入进入，给每个hla配备上
    
    train_dataset=HPIDataset(root='data', dataset=train_file + '_' + 'train', xd=train_hlas, peptide_key=train_peptides,
                               y=train_Y.astype(float), hla_contact_graph=hla_graph,hla_3d_graph=dataset_structure,pep_feature=train_pep_feature)
    
    vaild_dataset=HPIDataset(root='data', dataset=vaild_file + '_' + 'dev', xd=vaild_hlas, peptide_key=vaild_peptides,
                               y=vaild_Y.astype(float), hla_contact_graph=hla_graph,hla_3d_graph=dataset_structure,pep_feature=vaild_pep_feature)
    
    test_dataset=HPIDataset(root='data', dataset=test_file + '_' + 'dev', xd=test_hlas, peptide_key=test_peptides,
                               y=test_Y.astype(float), hla_contact_graph=hla_graph,hla_3d_graph=dataset_structure,pep_feature=test_pep_feature)

    return train_dataset, vaild_dataset,test_dataset,all_hla_graph


def train_predict_test_div_pep(train_file,vaild_file,test_file,dataset_structure,seed):    #数据集应该为未划分训练集测试集验证集的全数据集
    
    common_hla_file='/home1/layomi/项目代码/MMGHLA_CT/data/contact/common_hla_sequence.csv'
    train_entries,train_hla_keys,train_hla_dict,hla_dict=hla_key_and_setTrans(common_hla_file,train_file)
    vaild_entries,vaild_hla_keys,vaild_hla_dict,hla_dict=hla_key_and_setTrans(common_hla_file,vaild_file)
    test_entries,test_hla_keys,test_hla_dict,hla_dict=hla_key_and_setTrans_2(common_hla_file,test_file)
      
    train_p_entries,train_n_entries,train_peptide_type=P_or_N(train_entries)
    vaild_p_entries,vaild_n_entries,vaild_peptide_type=P_or_N(vaild_entries)
    test_p_entries,test_n_entries,test_peptide_type=P_or_N(test_entries)
    random.seed(seed)
    random.shuffle(train_entries)
    #random.shuffle(train_p_entries)
    #random.shuffle(train_n_entries)

    random.shuffle(vaild_entries)
    #random.shuffle(vaild_p_entries)
    #random.shuffle(vaild_n_entries)
    
    random.shuffle(test_entries)
    #random.shuffle(test_p_entries)
    #random.shuffle(test_n_entries)


    hla_full_sequence_dict=dict()
    full_seq_dict=json.load(open('/home1/layomi/项目代码/MMGHLA_CT/data/contact/common_hla_key_full_sequence.txt'), object_pairs_hook=OrderedDict)
    for key,value in full_seq_dict.items():
        key=int(key)
        hla_full_sequence_dict[key]=value
    
    # 构建接触图
    process_dir = os.path.join('/home1/layomi/项目代码/MMGHLA_CT', 'data/pre_process')
    hla_distance_dir = os.path.join(process_dir, 'contact/distance_map')  # numpy .npy file   这里给出接触图的路径
    # create hla graph
    hla_graph = dict()    
    for i in tqdm(range(len(hla_dict))):
        key = 1000+i
        seq=hla_full_sequence_dict[key]
        g_h = sequence_to_graph(key, seq, hla_distance_dir)
        hla_graph[key] = g_h
           
    train_hlas,train_peptides,train_Y=np.asarray(train_entries)[:,0],np.asarray(train_entries)[:,1],np.asarray(train_entries)[:,2]
    vaild_hlas,vaild_peptides,vaild_Y=np.asarray(vaild_entries)[:,0],np.asarray(vaild_entries)[:,1],np.asarray(vaild_entries)[:,2]
    test_hlas,test_peptides,test_Y=np.asarray(test_entries)[:,0],np.asarray(test_entries)[:,1],np.asarray(test_entries)[:,2]
    train_pep_feature=batch_seq_feature(train_peptides,15,33)
    vaild_pep_feature=batch_seq_feature(vaild_peptides,15,33)
    test_pep_feature=batch_seq_feature(test_peptides,15,33)
    #为类别图结点做初始化
    all_hla_graph=[]
    
    for key in sorted(hla_graph.keys()):
        hla_size,hla_features,hla_edge_index,hla_edges_weights=hla_graph[key]
        GCNData_hla = DATA.Data(x=torch.Tensor(hla_features),
                                edge_index=torch.LongTensor(hla_edge_index).transpose(1, 0),
                                edge_weight=torch.FloatTensor(hla_edges_weights))
        GCNData_hla.__setitem__('hla_size', torch.LongTensor([hla_size]))
        all_hla_graph.append(GCNData_hla)
        
    
    #这一段的意义是给训练测试数据集中每个hla配备了接触图，所以，我必须把3-D分子图也输入进入，给每个hla配备上
    
    train_dataset=HPIDataset_peps(root='data', dataset=train_file + '_' + 'train', xd=train_hlas, peptide_key=train_peptides,
                               y=train_Y.astype(float), hla_contact_graph=hla_graph,hla_3d_graph=dataset_structure,peps_feature=train_pep_feature)
    
    vaild_dataset=HPIDataset_peps(root='data', dataset=vaild_file + '_' + 'dev', xd=vaild_hlas, peptide_key=vaild_peptides,
                               y=vaild_Y.astype(float), hla_contact_graph=hla_graph,hla_3d_graph=dataset_structure,peps_feature=vaild_pep_feature)
    
    test_dataset=HPIDataset_peps(root='data', dataset=test_file + '_' + 'dev', xd=test_hlas, peptide_key=test_peptides,
                               y=test_Y.astype(float), hla_contact_graph=hla_graph,hla_3d_graph=dataset_structure,peps_feature=test_pep_feature)

    return train_dataset, vaild_dataset,test_dataset,all_hla_graph


class HPIDataset(InMemoryDataset):
    def __init__(self, root='/data', dataset='HPI',
                 xd=None, y=None, transform=None,
                 pre_transform=None, hla_contact_graph=None, peptide_key=None,hla_3d_graph=None):
        super(HPIDataset, self).__init__(root, transform, pre_transform)

        self.dataset=dataset
        self.hla=xd
        self.peptide_key=peptide_key    #peptide的key就是它本身
        self.y=y
        self.hla_contact_graph=hla_contact_graph
        self.hla_3d_graph=hla_3d_graph
        self.process(xd,peptide_key,y,hla_contact_graph,hla_3d_graph)

    @property
    def raw_file_names(self):
        pass
        # return ['some_file_1', 'some_file_2', ...]

    @property
    def processed_file_names(self):
        return [self.dataset + '_data_hla.pt', self.dataset + '_data_pep.pt']

    def download(self):
        # Download to `self.raw_dir`.
        pass

    def _download(self):
        pass

    def _process(self):
        if not os.path.exists(self.processed_dir):
            os.makedirs(self.processed_dir)

    def process(self, xd, peptide_key, y, hla_contact_graph,hla_3d_graph):
        assert (len(xd) == len(peptide_key) and len(xd) == len(y)), 'The three lists must have the same length!'
        data_list_hlacontact = []
        data_list_hla3D=[]
        data_list_pep = []
        data_len = len(xd)
        hla_key=[]
        for i in tqdm(range(data_len)):
            hla = int(xd[i])
            pep_key = peptide_key[i]
            labels = y[i]
            #contact_graph_data
            hla_size,hla_features,hla_edge_index,hla_edges_weights=hla_contact_graph[hla]
            ContactData_hla = DATA.Data(x=torch.Tensor(hla_features),
                                    edge_index=torch.LongTensor(hla_edge_index).transpose(1, 0),
                                    edge_weight=torch.FloatTensor(hla_edges_weights),
                                    y=torch.FloatTensor([labels]))
            ContactData_hla.__setitem__('hla_size', torch.LongTensor([hla_size]))
            
            #3-d-mol-data
            ThreeD_hla=hla_3d_graph[hla-1000]  #ThreeD_hla type=orch_geometric.data.Data
            
            data_list_hlacontact.append(ContactData_hla)
            data_list_hla3D.append(ThreeD_hla)
            data_list_pep.append(pep_key)
            hla_key.append(hla)

           
        self.data_hla_contact = data_list_hlacontact
        self.data_hla_3D=data_list_hla3D
        self.data_pep = data_list_pep
        self.data_hla_key=hla_key
        
        
class HPIDataset_peps(InMemoryDataset):
    def __init__(self, root='/data', dataset='HPI',
                 xd=None, y=None, transform=None,
                 pre_transform=None, hla_contact_graph=None, peptide_key=None,hla_3d_graph=None,peps_feature=None):
        super(HPIDataset_peps, self).__init__(root, transform, pre_transform)

        self.dataset=dataset
        self.hla=xd
        self.peptide_key=peptide_key    #peptide的key就是它本身
        self.y=y
        self.hla_contact_graph=hla_contact_graph
        self.hla_3d_graph=hla_3d_graph
        self.peps_feature=peps_feature
        self.process(xd,peptide_key,y,hla_contact_graph,hla_3d_graph,peps_feature)

    @property
    def raw_file_names(self):
        pass
        # return ['some_file_1', 'some_file_2', ...]

    @property
    def processed_file_names(self):
        return [self.dataset + '_data_hla.pt', self.dataset + '_data_pep.pt']

    def download(self):
        # Download to `self.raw_dir`.
        pass

    def _download(self):
        pass

    def _process(self):
        if not os.path.exists(self.processed_dir):
            os.makedirs(self.processed_dir)

    def process(self, xd, peptide_key, y, hla_contact_graph,hla_3d_graph,peps_feature):
        assert (len(xd) == len(peptide_key) and len(xd) == len(y)), 'The three lists must have the same length!'
        data_list_hlacontact = []
        data_list_hla3D=[]
        data_list_pep = []
        data_list_pep_feature=[]
        data_len = len(xd)
        hla_key=[]
        for i in tqdm(range(data_len)):
            hla = int(xd[i])
            pep_key = peptide_key[i]
            pep_feature=peps_feature[i]
            labels = y[i]
            #contact_graph_data
            hla_size,hla_features,hla_edge_index,hla_edges_weights=hla_contact_graph[hla]
            ContactData_hla = DATA.Data(x=torch.Tensor(hla_features),
                                    edge_index=torch.LongTensor(hla_edge_index).transpose(1, 0),
                                    edge_weight=torch.FloatTensor(hla_edges_weights),
                                    y=torch.FloatTensor([labels]))
            ContactData_hla.__setitem__('hla_size', torch.LongTensor([hla_size]))
            
            #3-d-mol-data
            ThreeD_hla=hla_3d_graph[hla]  #ThreeD_hla type=orch_geometric.data.Data
            
            
            
            data_list_hlacontact.append(ContactData_hla)
            data_list_hla3D.append(ThreeD_hla)
            data_list_pep.append(pep_key)
            data_list_pep_feature.append(pep_feature)
            hla_key.append(hla)

           
        self.data_hla_contact = data_list_hlacontact
        self.data_hla_3D=data_list_hla3D
        self.data_pep = data_list_pep
        self.peps_feature=data_list_pep_feature
        self.data_hla_key=hla_key
        
        
    def __len__(self):
        return len(self.y)

    def __getitem__(self, idx):
        # return GNNData_mol, GNNData_pro
        return self.data_hla_contact[idx], self.data_hla_3D[idx],self.data_pep[idx],self.data_hla_key[idx],self.peps_feature[idx]

class HPIDataset_peps_new(InMemoryDataset):
    def __init__(self, root='/data', dataset='HPI',
                 xd=None, y=None, transform=None,
                 pre_transform=None, hla_contact_graph=None, peptide_key=None,hla_3d_graph=None,peps_feature=None,all_hla_len=None):
        super(HPIDataset_peps_new, self).__init__(root, transform, pre_transform)

        self.dataset=dataset
        self.hla=xd
        self.peptide_key=peptide_key    #peptide的key就是它本身
        self.y=y
        self.hla_contact_graph=hla_contact_graph
        self.hla_3d_graph=hla_3d_graph
        self.peps_feature=peps_feature
        self.all_hla_len=all_hla_len
        self.process(xd,peptide_key,y,hla_contact_graph,hla_3d_graph,all_hla_len,peps_feature)

    @property
    def raw_file_names(self):
        pass
        # return ['some_file_1', 'some_file_2', ...]

    @property
    def processed_file_names(self):
        return [self.dataset + '_data_hla.pt', self.dataset + '_data_pep.pt']

    def download(self):
        # Download to `self.raw_dir`.
        pass

    def _download(self):
        pass

    def _process(self):
        if not os.path.exists(self.processed_dir):
            os.makedirs(self.processed_dir)

    def process(self, xd, peptide_key, y, hla_contact_graph,hla_3d_graph,all_hla_len,peps_feature):
        assert (len(xd) == len(peptide_key) and len(xd) == len(y)), 'The three lists must have the same length!'
        data_list_hlacontact = []
        data_list_hla3D=[]
        data_list_pep = []
        data_list_pep_feature=[]
        data_len = len(xd)
        #hla_key=[]
        for i in tqdm(range(data_len)):
            hla = int(xd[i])
            pep_key = peptide_key[i]
            pep_feature=peps_feature[i]
            labels = y[i]
            #contact_graph_data
            hla_size,hla_features,hla_edge_index,hla_edges_weights=hla_contact_graph[hla]
            ContactData_hla = DATA.Data(x=torch.Tensor(hla_features),
                                    edge_index=torch.LongTensor(hla_edge_index).transpose(1, 0),
                                    edge_weight=torch.FloatTensor(hla_edges_weights),hla_len=all_hla_len[hla],hla_key=hla,
                                    y=torch.FloatTensor([labels]))
            ContactData_hla.__setitem__('hla_size', torch.LongTensor([hla_size]))
            
            #3-d-mol-data
            ThreeD_hla=hla_3d_graph[hla]  #ThreeD_hla type=orch_geometric.data.Data
            #Data_pep=DATA.Data(x=pep_feature,sequence=peptide_key,pep_len=len(peptide_key))
            Data_pep = {
                        'x': pep_feature,
                        'sequence': pep_feature,
                        'length': len(pep_feature)
                    }
            
            data_list_hlacontact.append(ContactData_hla)
            data_list_hla3D.append(ThreeD_hla)
            
            data_list_pep.append(Data_pep)
            #data_list_pep_feature.append(pep_feature)
            #hla_key.append(hla)

           
        self.data_hla_contact = data_list_hlacontact
        self.data_hla_3D=data_list_hla3D
        self.data_pep=data_list_pep
        #self.peps_feature=data_list_pep_feature
        #self.data_hla_key=hla_key
        
        
    def __len__(self):
        return len(self.y)

    def __getitem__(self, idx):
        # return GNNData_mol, GNNData_pro
        return self.data_hla_contact[idx], self.data_hla_3D[idx],self.data_pep[idx]
    
class HPIDataset_peps_new_blousm(InMemoryDataset):
    def __init__(self, root='/data', dataset='HPI',
                 xd=None, y=None, transform=None,
                 pre_transform=None, hla_contact_graph=None, peptide_key=None,hla_3d_graph=None,peps_feature=None,all_hla_len=None):
        super(HPIDataset_peps_new_blousm, self).__init__(root, transform, pre_transform)

        self.dataset=dataset
        self.hla=xd
        self.peptide_key=peptide_key    #peptide的key就是它本身
        self.y=y
        self.hla_contact_graph=hla_contact_graph
        self.hla_3d_graph=hla_3d_graph
        self.peps_feature=peps_feature
        self.all_hla_len=all_hla_len
        self.process(xd,peptide_key,y,hla_contact_graph,hla_3d_graph,all_hla_len,peps_feature)

    @property
    def raw_file_names(self):
        pass
        # return ['some_file_1', 'some_file_2', ...]

    @property
    def processed_file_names(self):
        return [self.dataset + '_data_hla.pt', self.dataset + '_data_pep.pt']

    def download(self):
        # Download to `self.raw_dir`.
        pass

    def _download(self):
        pass

    def _process(self):
        if not os.path.exists(self.processed_dir):
            os.makedirs(self.processed_dir)

    def process(self, xd, peptide_key, y, hla_contact_graph,hla_3d_graph,all_hla_len,peps_feature):
        assert (len(xd) == len(peptide_key) and len(xd) == len(y)), 'The three lists must have the same length!'
        data_list_hlacontact = []
        data_list_hla3D=[]
        data_list_pep = []
        data_list_pep_feature=[]
        data_len = len(xd)
        #hla_key=[]
        for i in tqdm(range(data_len)):
            hla = int(xd[i])
            pep_key = peptide_key[i]
            pep_feature=peps_feature[i]
            labels = y[i]
            #contact_graph_data
            hla_size,hla_features,hla_edge_index,hla_edges_weights=hla_contact_graph[hla]
            ContactData_hla = DATA.Data(x=torch.Tensor(hla_features),
                                    edge_index=torch.LongTensor(hla_edge_index).transpose(1, 0),
                                    edge_weight=torch.FloatTensor(hla_edges_weights),hla_len=all_hla_len[hla],hla_key=hla,
                                    y=torch.FloatTensor([labels]))
            ContactData_hla.__setitem__('hla_size', torch.LongTensor([hla_size]))
            
            #3-d-mol-data
            ThreeD_hla=hla_3d_graph[hla]  #ThreeD_hla type=orch_geometric.data.Data
            #Data_pep=DATA.Data(x=pep_feature,sequence=peptide_key,pep_len=len(peptide_key))
            Data_pep = {
                        'x': pep_feature,
                        'sequence': pep_feature,
                        'length': len(pep_feature)
                    }
            
            data_list_hlacontact.append(ContactData_hla)
            data_list_hla3D.append(ThreeD_hla)
            
            data_list_pep.append(Data_pep)
            #data_list_pep_feature.append(pep_feature)
            #hla_key.append(hla)

           
        self.data_hla_contact = data_list_hlacontact
        self.data_hla_3D=data_list_hla3D
        self.data_pep=data_list_pep
        #self.peps_feature=data_list_pep_feature
        #self.data_hla_key=hla_key
        
        
    def __len__(self):
        return len(self.y)

    def __getitem__(self, idx):
        # return GNNData_mol, GNNData_pro
        return self.data_hla_contact[idx], self.data_hla_3D[idx],self.data_pep[idx]
    
    
    



def categraph_pack(hla_contact_graph,hla_3d_grpah):  #输入的两个都是分子图的list
    
    #为类别图结点做初始化
    all_hla_graph=[]
    
    for key in sorted(hla_graph.keys()):
        hla_size,hla_features,hla_edge_index,hla_edges_weights=hla_graph[key]
        hla_3d_graph[i]
        GCNData_hla = DATA.Data(x=torch.Tensor(hla_features),
                                edge_index=torch.LongTensor(hla_edge_index).transpose(1, 0),
                                edge_weight=torch.FloatTensor(hla_edges_weights))
        GCNData_hla.__setitem__('hla_size', torch.LongTensor([hla_size]))
        all_hla_graph.append(GCNData_hla)
        
        data = torch_geometric.data.Data(x=X_ca, seq=seq, seq_len=seq_len, name=name,
                                         node_s=node_s, node_v=node_v,
                                         edge_s=edge_s, edge_v=edge_v,
                                         edge_index=edge_index, mask=mask)
        
        
        
        
        
def add_physical_chemical_noise(properties, mean=0, std=0.01):
    properties = torch.tensor(properties)
    noise = np.random.normal(mean, std, properties.shape)
    return properties + noise





def read_binding_data_new(path,pseq_dict,global_args):
    '''
    read binding data for peptide-MHC pairs, which are used to train the network
    Data downloaded from http://tools.immuneepitope.org/mhci/download/
    Args:
        1. path: path to the data file binding_data_train.txt
        2. pseq_dict: the output of pseudo_seq()
    Return values:
        1. data_dict, format: {MHC_allele_name:
            [encoded pep sequence, encoded MHC pseudo sequence, len of pep, affinity]}
    '''
    [blosum_matrix, aa, main_dir, output_path] = global_args
    data_dict = {}
    with open(path,'r') as f:
        data=pd.read_csv(f)
    f.close()
    data_quanbu=np.array(data)[1:,]
    #根据hla名称找到hla序列 
    seq_dict_24=dict()  
    hla_blosum_dict=dict()
    for allele in seq_dict.keys():
        seq_dict[allele] = seq_dict[allele][24:]   
    for allele in seq_dict.keys():
        hla_blosum=[]
        for ra in seq_dict_24[allele]:
            hla_blosum.append(blosum_matrix[aa[ra]])
        hla_blosum_dict[allele]=hla_blosum

    for line in data_quanbu:
        allele = line[0]
        if allele in hla_blosum_dict.keys():
            #affinity = 1-log(float(info[5]))/log(50000)
            affinity=line[2]
            pep = line[1]#Sequence of the peptide in the form of a string, like "AAVFPPLEP"
            pep_blosum = []#Encoded peptide seuqence
            for residue_index in range(15):
                #Encode the peptide sequence in the 1-12 columns, with the N-terminal aligned to the left end
                #If the peptide is shorter than 12 residues, the remaining positions on
                #the rightare filled will zero-padding
                if residue_index < len(pep):
                    pep_blosum.append(blosum_matrix[aa[pep[residue_index]]])
                else:
                    pep_blosum.append(np.zeros(20))
            for residue_index in range(15):
                #Encode the peptide sequence in the 13-24 columns, with the C-terminal aligned to the right end
                #If the peptide is shorter than 12 residues, the remaining positions on
                #the left are filled will zero-padding
                if 15 - residue_index > len(pep):
                    pep_blosum.append(np.zeros(20)) 
                else:
                    pep_blosum.append(blosum_matrix[aa[pep[len(pep) - 15 + residue_index]]])
                    
            #new_data = [encoded pep sequence, encoded MHC pseudo sequence, len of pep, affinity]
            new_data = [pep_blosum, hla_blosum_dict[allele], affinity, len(pep), pep]
            if allele not in data_dict.keys():
                data_dict[allele] = [new_data]
            else:
                data_dict[allele].append(new_data)
            #print('len(data_dict.keys())',len(data_dict.keys()))

    print ("Finished reading binding data")
    return data_dict
'''
def read_hla_blousm(input_key):  #通过key得到序列然后得到blousm编码
    full_seq_dict=json.load(open('/home1/layomi/项目代码/MMGHLA_CT/data/contact/common_hla_key_full_sequence_new.txt'), object_pairs_hook=OrderedDict)
    for key,value in full_seq_dict.items():
        key=int(key)
        hla_full_sequence_dict[key]=value[24:]
        
    seq_dict_24=dict()  
    hla_blosum_dict=dict()
    for key in hla_full_sequence_dict.keys():
        seq_dict_24[key] = seq_dict[allele][24:]   
    for allele in seq_dict.keys():
        hla_blosum=[]
        for ra in seq_dict_24[allele]:
            hla_blosum.append(blosum_matrix[aa[ra]])
        hla_blosum_dict[allele]=hla_blosum
'''
def read_hla_blousm():  #得到所有序列的blousm编码
    hla_full_sequence_dict=dict()
    full_seq_dict=json.load(open('../data/contact/common_hla_key_full_sequence_new.txt'), object_pairs_hook=OrderedDict)
    for key,value in full_seq_dict.items():
        key=int(key)
        hla_full_sequence_dict[key]=value[24:]
        
    seq_dict_24=hla_full_sequence_dict
    hla_key_blosum_dict=dict()
    for allele in seq_dict_24.keys():
        hla_blosum=[]
        for ra in seq_dict_24[allele]:
            hla_blosum.append(blosum_matrix[aa[ra]])
        hla_blousm = np.array(hla_blosum)
        
        hla_key_blosum_dict[allele]=hla_blousm
    
    return hla_key_blosum_dict
    
def test_data_div(test_file):
    #得到文件中hla键的顺序
    common_hla_file='../data/contact/common_hla_sequence.csv'
    test_entries,test_hla_keys,test_hla_dict,hla_dict=hla_key_and_setTrans(common_hla_file,test_file)
    
    hla_full_sequence_dict=dict()
    full_seq_dict=json.load(open('../data/contact/common_hla_key_full_sequence_new.txt'), object_pairs_hook=OrderedDict)
    for key,value in full_seq_dict.items():
        key=int(key)
        hla_full_sequence_dict[key]=value
        
    # 构建接触图/home/layomi/drive1/项目代/home/layomi/drive1/项目代码/MMGHLA_Classification_Topography码/MMGHLA_Classification_Topography
    process_dir = os.path.join('..', 'data/pre_process')
    hla_distance_dir = os.path.join(process_dir, 'contact/distance_map')  # numpy .npy file   这里给出接触图的路径
    hla_key_blousm_dict=read_hla_blousm()   #对hla进行blousm编码
    hla_graph = dict()    
    all_hla_len=[]
    for i in tqdm(range(len(hla_dict))):
        key = i
        seq=hla_full_sequence_dict[key]
        g_h = sequence_to_graph(key, seq, hla_distance_dir)
        hla_graph[key] = g_h
        all_hla_length=len(seq)-24
        all_hla_len.append(all_hla_length)
   
    
    test_hlas,test_peptides,test_Y=np.asarray(test_entries)[:,0],np.asarray(test_entries)[:,1],np.asarray(test_entries)[:,2]
    cath = CATHDataset(os.path.join('/home1/layomi/项目代码/MMGHLA_CT_blousm/data/aphlafold2', 'structure.jsonl'))
    dataset_structure = transform_data(cath.data, max_pro_seq_len)
   
    test_pep_feature=batch_seq_feature_only_onehot(test_peptides,15,21)
    
    test_dataset=HPIDataset_peps_new_only_onehot(xh=test_hlas, peptide_key=test_peptides,
                               y=test_Y.astype(float), hla_contact_graph=hla_graph,hla_3d_graph=dataset_structure,peps_feature=test_pep_feature,all_hla_len=all_hla_len
                               )
    return test_dataset

