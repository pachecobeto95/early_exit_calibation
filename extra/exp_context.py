import torchvision.transforms as transforms
import torchvision
from torchvision import datasets, transforms
from torch.utils.data.sampler import SubsetRandomSampler
from torchvision.utils import save_image
import os, sys, time, math, os
from torchvision import transforms, utils, datasets
from torch.utils.data import Dataset, DataLoader, SubsetRandomSampler, WeightedRandomSampler
from torch.utils.data import random_split
from PIL import Image
import torch
import numpy as np
import torch.nn as nn
import torch.optim as optim
import torch.nn.functional as F
from torch.autograd import Variable
from itertools import product
import pandas as pd
import torchvision.models as models
from torch.optim.lr_scheduler import _LRScheduler
from torch.optim import lr_scheduler
from torchvision import datasets, transforms
from pthflops import count_ops
from pthflops import count_ops
from torch import Tensor
from typing import Callable, Any, Optional, List, Type, Union
import torch.nn.init as init
import functools
from tqdm import tqdm
from scipy.stats import entropy


def cifar_10(batch_size_train, batch_size_test, input_resize, input_crop):

  #To normalize the input images data.
  mean = [0.457342265910642, 0.4387686270106377, 0.4073427106250871]
  std =  [0.26753769276329037, 0.2638145880487105, 0.2776826934044154]

  # Note that we apply data augmentation in the training dataset.
  transformations_train = transforms.Compose([transforms.Resize(256),
                                              transforms.CenterCrop(224),
                                              transforms.RandomHorizontalFlip(p = 0.25),
                                              transforms.RandomRotation(25),
                                              transforms.ToTensor(), 
                                              transforms.Normalize(mean = mean, std = std),
                                              ])

  # Note that we do not apply data augmentation in the test dataset.
  transformations_test = transforms.Compose([transforms.Resize(256),
                                             transforms.CenterCrop(224), 
                                             transforms.ToTensor(), 
                                             transforms.Normalize(mean = mean, std = std),
                                             ])
  
  train_set = datasets.CIFAR10(root=".", train=True, download=True, transform=transformations_train)
  test_set = datasets.CIFAR10(root=".", train=False, download=True, transform=transformations_test)

  train_loader = DataLoader(train_set, batch_size_train, shuffle=True, num_workers=4, pin_memory=True)
  test_loader = DataLoader(test_set, batch_size_test, num_workers=4, pin_memory=True)

  return train_loader, test_loader

class Branch(nn.Module):
	def __init__(self, layer):
		super(Branch, self).__init__()
		if(layer is not None):
			self.layer = nn.Sequential(*layer)
		else:
			self.layer = layer
	def forward(self, x):
		if(self.layer is None):
			return x
		else:
			return self.layer(x)

def norm():
  norm_layer = [nn.ReLU(inplace=True), nn.MaxPool2d(kernel_size=3, stride=2),
                nn.LocalResponseNorm(size=3, alpha=5e-05, beta=0.75)]
  return norm_layer

conv = lambda n: [nn.Conv2d(n, 32, kernel_size=3, stride=1, padding=1), nn.ReLU(inplace=True)]
cap =  lambda n: [nn.MaxPool2d(kernel_size=3), Flatten(), nn.Linear(n, 10)]

class Flatten(nn.Module):
    def __init__(self):
        super(Flatten, self).__init__()
    
    def forward(self, x):
        # Do your print / debug stuff here
        x = x.view(x.size(0), -1)
        return x


class PrintLayer(nn.Module):
    def __init__(self):
        super(PrintLayer, self).__init__()
    
    def forward(self, x):
        # Do your print / debug stuff here
        print(x.shape)
        return x

class B_AlexNet(nn.Module):
  def __init__(self, branch1, branch2, n_classes, pretrained=True):
    super(B_AlexNet, self).__init__()
    self.stages = nn.ModuleList()
    self.layers = nn.ModuleList()
    self.exits = nn.ModuleList()
    insert_branches = [2]
    self.stage_id = 0


    backbone_model = models.alexnet(pretrained=pretrained)
    backbone_model_features = backbone_model.features

    for i, layer in enumerate(backbone_model_features):
      self.layers.append(layer)
      if (i == insert_branches[0]):
        self.add_exit_point(branch1)
    
    self.layers.append(nn.AdaptiveAvgPool2d(output_size=(6, 6)))    
    self.stages.append(nn.Sequential(*self.layers))
    del self.layers   
    self.classifier = backbone_model.classifier
    self.classifier[1] = nn.Linear(9216, 4096)
    self.classifier[4] = nn.Linear(4096, 1024)
    self.classifier[6] = nn.Linear(1024, n_classes)    
    self.softmax = nn.Softmax(dim=1)

  def add_exit_point(self, branch1):
    self.stages.append(nn.Sequential(*self.layers))
    self.exits.append(nn.Sequential(*branch1))
    self.layers = nn.ModuleList()
    self.stage_id += 1    


  def forwardEval(self, x):
    """
    This method is used to experiment of early-exit DNNs.
    """
    conf_list, class_list  = [], []
    n_exits = 1 + 1

    for i, exitBlock in enumerate(self.exits):
      x = self.stages[i](x)

      output_branch = exitBlock(x)
      conf_branch, infered_class_branch = torch.max(self.softmax(output_branch), 1)
      conf_list.append(conf_branch.item()), class_list.append(infered_class_branch.item())

    x = self.stages[-1](x)
    
    x = torch.flatten(x, 1)

    output = self.classifier(x)
    conf, infered_class = torch.max(self.softmax(output), 1)
    conf_list.append(conf.item()), class_list.append(infered_class.item())
    return conf_list, class_list


  def forwardMain(self, x):
    for i, stage in enumerate(self.exits):
      x = self.stages[i](x)

    x = self.stages[-1](x)
    
    x = torch.flatten(x, 1)

    output = self.classifier(x)
    _, infered_class = torch.max(self.softmax(output), 1)
    return output, infered_class

  def forwardBranchesTrain(self, x, i):
    n_exits = len(self.exits)

    if(i < n_exits):
      intermediate_model = nn.Sequential(*self.stages[:(i+1)])
      x = intermediate_model(x)
      output_branch = self.exits[i](x)
      _, infered_class = torch.max(self.softmax(output_branch), 1)
      return output_branch, infered_class

    else:
      intermediate_model = nn.Sequential(*self.stages[:(i+1)])
      x = intermediate_model(x)
      x = torch.flatten(x, 1)
      output = self.classifier(x)
      _, infered_class = torch.max(self.softmax(output), 1)
      return output, infered_class


class DNN(nn.Module):
  def __init__(self, layer_list):
    super(DNN, self).__init__()
    self.layer_list = layer_list
    self.layers = nn.ModuleList(self.layer_list)

  def forward(self, inputs):
    for i in range(len(self.layer_list)):
      inputs = self.layers[i](inputs)
    return inputs

class BranchyNet:
  def __init__(self, network, device, weight_list=None, thresholdExits=None, percentTestExits=.9, percentTrainKeeps=.5, lr_main=0.001, 
               lr_branches=0.001, momentum=0.9, weight_decay=0.0001, alpha=0.001, confidence_metric="confidence", 
               opt="Adam", joint=True, verbose=False):
    
    self.network = network
    self.lr_main = lr_main
    self.lr_branches = lr_branches
    self.momentum = momentum
    self.opt = opt
    self.weight_decay = weight_decay
    self.alpha = alpha
    self.joint = joint
    self.verbose = verbose
    self.thresholdExits = thresholdExits
    self.percentTestExits = percentTestExits
    self.percentTrainKeeps = percentTrainKeeps
    self.gpu = False
    self.criterion = nn.CrossEntropyLoss()
    self.weight_list = weight_list
    self.device = device
    self.confidence_metric = confidence_metric
    steps = 10

    if (weight_list is None):
      #self.weight_list = np.ones(len(self.network.stages))
      self.weight_list = np.linspace(1, 0.3, len(self.network.stages))

    
    if (self.confidence_metric == "confidence"):
      self.confidence_metric = self.compute_confidence
      self.shouldExist = self.verify_confidence

    elif (self.confidence_metric == "entropy"):
      self.confidence_metric = self.compute_entropy
      self.shouldExist = self.verify_entropy

    else:
      raise NotImplementedError("This confidence metric is not supported.")

    self.main = []
    self.models = []
    """
    for layer in network:

      if not isinstance(layer,Branch):
        self.main.append(layer)
      else:
        self.models.append(list(self.main)+[layer])

  
    self.main = nn.Sequential(*nn.ModuleList(self.main))
    self.models = [nn.Sequential(*nn.ModuleList(model)) for model in self.models]

    if (self.opt == "Adam"):
      self.optimizer_main = optim.Adam(self.main.parameters(), lr=self.lr, weight_decay=self.weight_decay)
    else:
      self.optimizer_main = optim.SGD(self.main.parameters(), lr=self.lr, momentum=self.momentum, weight_decay=self.weight_decay)
    """


    if (self.opt == "Adam"):
      self.optimizer_main = optim.Adam([{"params":self.network.stages.parameters()},
                                      {"params":self.network.classifier.parameters()}], lr=self.lr_main, betas=(0.9, 0.999), eps=1e-08, 
                                       weight_decay=self.weight_decay)

    else:
      self.optimizer_main = optim.Adam([{"params":self.network.stages.parameters()},
                                       {"params":self.network.classifier.parameters()}], lr=self.lr_main, momentum=self.momentum, 
                                      weight_decay=self.weight_decay)


    self.scheduler_main = optim.lr_scheduler.CosineAnnealingLR(self.optimizer_main, steps, eta_min=0, last_epoch=-1, verbose=True)


    self.optimizer_list = []
    self.scheduler_list = []

    for i in range(len(self.network.stages)):
      if(i == len(self.network.stages)-1):
        opt_branch = optim.Adam([{"params":self.network.stages.parameters()},
                                {"params":self.network.classifier.parameters()}], lr=self.lr_main, betas=(0.9, 0.999), 
                              weight_decay=self.weight_decay)

      else:
        opt_branch = optim.Adam([{"params":self.network.stages[i].parameters()},
                              {"params":self.network.exits.parameters()}], lr=self.lr_branches, betas=(0.9, 0.999), 
                              weight_decay=self.weight_decay)

      self.optimizer_list.append(opt_branch)
      scheduler_branches = optim.lr_scheduler.CosineAnnealingLR(opt_branch, steps, eta_min=0, last_epoch=-1, verbose=True)
      self.scheduler_list.append(scheduler_branches)

  def training(self):
    self.network.stages.train()
    self.network.exits.train()
    self.network.classifier.train()

  def testing(self):
    self.network.stages.eval()
    self.network.exits.eval()
    self.network.classifier.eval()

  def to_device(self):
    self.network.stages = self.network.stages.to(self.device)
    self.network.exits = self.network.exits.to(self.device)
    self.network.classifier = self.network.classifier.to(self.device)

  def compute_entropy(self, softmax_output):
    entropy_value = np.array([entropy(output) for output in softmax_output.cpu().detach().numpy()])
    return entropy_value 

  def verify_entropy(self, entropy_value, thresholdExitsValue):
    return entropy_value <= thresholdExitsValue

  def verify_confidence(self, confidence_value, thresholdExitsValue):
    return confidence_value >= thresholdExitsValue

  def compute_confidence(self, softmax_output):
    confidence_value, _ = torch.max(softmax_output, 1)
    return confidence_value.cpu().detach().numpy()

  def train_main(self, x, t):
    self.optimizer_main.zero_grad()
    output, infered_class = self.network.forwardMain(x)
    loss = self.criterion(output, t)
    loss.backward()
    self.optimizer_main.step()

    acc = 100*infered_class.eq(t.view_as(infered_class)).sum().item()/t.size(0)    
    return loss.item(), acc

  def val_main(self, x, t):
    output, infered_class = self.network.forwardMain(x)
    loss = self.criterion(output, t)
    acc = 100*infered_class.eq(t.view_as(infered_class)).sum().item()/t.size(0)    

    return loss.item(), acc

  def val_branches(self, x, t):
    remainingXVar = x
    remainingTVar = t

    numexits, losses, acc_list, acc_branches_list = [], [], [], []
    
    n_models = len(self.network.stages)
    
    n_samples = x.data.shape[0]

    softmax = nn.Softmax(dim=1)

    for i in range(n_models):
      if (remainingXVar is None) or (remainingTVar is None):
        numexits.append(0), accuracies.append(0)
        break

      output_branch, class_infered_branch = self.network.forwardBranchesTrain(remainingXVar, i)
      
      softmax_output = softmax(output_branch)
      
      confidence_measure = self.confidence_metric(softmax_output)
      
      idx = np.zeros(confidence_measure.shape[0],dtype=bool)

      if (i == n_models-1):
        idx = np.ones(confidence_measure.shape[0],dtype=bool)
        numexit = sum(idx)
        
      else:
        if (self.thresholdExits is not None):
          min_ent = 0
          if (isinstance(self.thresholdExits, list)):
            idx[self.shouldExist(confidence_measure, self.thresholdExits[i])] = True
            numexit = sum(idx)
          else:
            idx[self.shouldExist(confidence_measure, self.thresholdExits)] = True
            numexit = sum(idx)
        
        else:
          if (isinstance(self.percentTestExits, list)):
            numexit = int((self.percentTestExits[i])*numsamples)
          else:
            numexit = int(self.percentTestExits*confidence_measure.shape[0])

          esorted = confidence_measure.argsort()
          idx[esorted[:numexit]] = True
            
      total = confidence_measure.shape[0]
      numkeep = total-numexit
      numexits.append(numexit)

      xdata = remainingXVar.data
      tdata = remainingTVar.data

      if (numkeep > 0):
        xdata_keep = xdata[~idx]
        tdata_keep = tdata[~idx]
        remainingXVar = Variable(xdata_keep, requires_grad=False).to(self.device)
        remainingTVar = Variable(tdata_keep, requires_grad=False).to(self.device)

      else:
        remainingXVar = None
        remainingTVar = None


      if (numexit > 0):
        xdata_exit = xdata[idx]
        tdata_exit = tdata[idx]                
        
        exitXVar = Variable(xdata_exit, requires_grad=False).to(self.device)
        exitTVar = Variable(tdata_exit, requires_grad=False).to(self.device)
                

        exit_output, class_infered_branch = self.network.forwardBranchesTrain(exitXVar, i)
                
        accuracy_branch = 100*class_infered_branch.eq(exitTVar.view_as(class_infered_branch)).sum().item()/exitTVar.size(0)
        acc_branches_list.append(accuracy_branch)

        loss = self.criterion(exit_output, exitTVar)
        losses.append(loss)  

      else:
        acc_branches_list.append(0.), losses.append(0.)
                
    overall_acc = 0
    overall_loss = 0
    n_accumulated_exits = np.zeros(n_models)

    losses = [loss.item() for loss in losses]
    for i, (accuracy, loss) in enumerate(zip(acc_branches_list, losses)):
      overall_acc += accuracy*numexits[i]
      overall_loss += loss*numexits[i]
      
    overall_acc = overall_acc/np.sum(numexits)
    overall_loss = overall_loss/np.sum(numexits)

    return overall_loss, overall_acc, losses, acc_branches_list
  


  def train_branches(self, x, t):
    remainingXVar = x
    remainingTVar = t

    numexits, losses, acc_list = [], [], []
    
    n_models = len(self.network.stages)
    n_samples = x.data.shape[0]

    softmax = nn.Softmax(dim=1)

    for i in range(n_models):
      if (remainingXVar is None) or (remainingTVar is None):
        break
      
      output_branch, class_infered_branch = self.network.forwardBranchesTrain(remainingXVar, i)
      loss_branch = self.criterion(output_branch, remainingTVar)
      acc_branch = 100*class_infered_branch.eq(remainingTVar.view_as(class_infered_branch)).sum().item()/remainingTVar.size(0)    


      #if (i == n_models-1):
      #  continue
      losses.append(loss_branch)
      acc_list.append(acc_branch)
      
      softmax_output = softmax(output_branch)
      
      confidence_measure = self.confidence_metric(softmax_output)
      
      total = confidence_measure.shape[0]

      idx = np.zeros(total, dtype=bool)

      if (i == n_models-1):
        idx = np.ones(confidence_measure.shape[0], dtype=bool)
        numexit = sum(idx)
        
      else:
        if (self.thresholdExits is not None):
          
          if (isinstance(self.thresholdExits, list)):
            idx[self.shouldExist(confidence_measure, self.thresholdExits[i])] = True
            numexit = sum(idx)
          else:
            idx[self.shouldExist(confidence_measure, self.thresholdExits)] = True
            numexit = sum(idx)
        
        else:
          if (isinstance(self.percentTrainKeeps, list)):
            numkeep = (self.percentTrainKeeps[i])*numsamples

          else:
            numkeep = self.percentTrainKeeps*total
          
          numexit = int(total - numkeep)
          esorted = confidence_measure.argsort()
          idx[esorted[:numexit]] = True
            
      numkeep = int(total - numexit)
      numexits.append(numexit)

      xdata = remainingXVar.data
      tdata = remainingTVar.data

      if (numkeep > 0):
        xdata_keep = xdata[~idx]
        tdata_keep = tdata[~idx]

        remainingXVar = Variable(xdata_keep, requires_grad=False).to(self.device)
        remainingTVar = Variable(tdata_keep, requires_grad=False).to(self.device)

      else:
        remainingXVar = None
        remainingTVar = None


    #self.optimizer_main.zero_grad()
    [optimizer.zero_grad() for optimizer in self.optimizer_list]
    for i, (weight, loss) in enumerate(zip(self.weight_list, losses)):
      loss = weight*loss
      loss.backward()
            
    #self.optimizer_main.step()
    [optimizer.step() for optimizer in self.optimizer_list]

    loss_branches = np.array([loss.item() for loss in losses])
    acc_list = np.array(acc_list)

    overall_acc = 0
    overall_loss = 0
    for i, (acc, loss) in enumerate(zip(acc_list, loss_branches)):
      overall_acc += acc*numexits[i]
      overall_loss += loss*numexits[i]

    overall_acc = overall_acc/np.sum(numexits)
    overall_loss = overall_loss/np.sum(numexits)

    return overall_loss, overall_acc, loss_branches, acc_list



def build_b_alexnet(device, n_classes):
  pretrained = False
  branch1 = norm() + conv(64) + conv(32) + cap(512)
  b_alexnet = B_AlexNet(branch1, None, n_classes, pretrained)
  branchynet = BranchyNet(b_alexnet, device)
  return branchynet


def experiment_context_inference(model, test_loader, classes_list, n_branches, device, saveResultsPath):
  df_result = pd.DataFrame()

  n_exits = n_branches + 1
  conf_branches_list, infered_class_branches_list = [], []
  target_list, label_list, inferred_label_list = [], [], []
  correct_list, delta_confidence_list = [], []

  model.testing()
  with torch.no_grad():
    for i, (data, target) in tqdm(enumerate(test_loader, 1)):

      data, target = data.to(device), target.float().to(device)

      conf_branches, infered_class_branches = model.network.forwardEval(data)
      delta_confidence = conf_branches[-1] - conf_branches[0] 
      
      conf_branches_list.append(conf_branches), infered_class_branches_list.append(infered_class_branches)     
      delta_confidence_list.append(delta_confidence)
      target_list.append(target.item()), label_list.append(classes_list[int(target.item())])      
      inferred_label_list.append([classes_list[int(infered_class_branches[i].item())] for i in range(n_exits)])
      correct_list.append([infered_class_branches[i].eq(target.view_as(infered_class_branches[i])).sum().item() for i in range(n_exits)])


      del data, target
      torch.cuda.empty_cache()

  conf_branches_list = np.array(conf_branches_list)
  infered_class_branches_list = np.array(infered_class_branches_list)
  correct_list = np.array(correct_list)
  inferred_label_list = np.array(inferred_label_list)

  results = {"delta_conf": delta_confidence_list,
             "label": label_list,
             "target": target_list}

  for i in range(n_exits):
    results.update({"conf_branch_%s"%(i+1): conf_branches_list[:, i],
                    "infered_class_branches_%s"%(i+1): infered_class_branches_list[:, i],
                    "correct_branch_%s"%(i+1): correct_list[:, i],
                    "infered_label_branches_%s"%(i+1): inferred_label_list[:, i]})
  
  df_results = pd.DataFrame(np.array(list(results.values())).T, columns=list(results.keys()))
  df_results.to_csv(saveResultsPath)


n_classes = 10
pretrained = True
fine_tune = True
n_branches = 1
input_dim = 32
device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
input_shape = (3, input_dim, input_dim)
distribution = "linear"
exit_type = "bnpool"
dataset_name = "cifar_10"
model_name = "alexnet"
model_id = 3

classes_list = ['plane', 'car', 'bird', 'cat','deer', 'dog', 'frog', 'horse', 'ship', 'truck']

result_path = os.path.join(".")
model_path = os.path.join(result_path, "branches_%s.pth"%(model_id))
save_result_path_samples = os.path.join(result_path, "inference_exp_ucb_%s.csv"%(model_id)) 


batch_size_train = 512
batch_size_test = 1
input_resize, input_crop = 256, 224
train_loader, test_loader = cifar_10(batch_size_train, batch_size_test, input_resize, input_crop)

branchynet = build_b_alexnet(device, n_classes)
branchynet.to_device()

experiment_context_inference(branchynet, test_loader, classes_list, n_branches, device, save_result_path_samples)
