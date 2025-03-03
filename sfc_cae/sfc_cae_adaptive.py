"""
This module contains the of a space-filling convolutional autoencoder to handle adaptive dataset.
Author: Jin Yu
Github handle: acse-jy220
"""

import torch  # Pytorch
import torch.nn as nn  # Neural network module
import torch.nn.functional as fn  # Function module
# import sfc_interpolate as interpol 
from .utils import *

###############################################################   Encoder Part ###################################################################

class SFC_CAE_Encoder_Adaptive(nn.Module): 
  def __init__(self, 
               input_size,
               dimension,
               components,
               structured,
               self_concat,
               nearest_neighbouring, 
               dims_latent, 
               sfc_nums,
               activation,
               variational,
               coords_dimension = None,
               force_initialising_param=None,
               sfc_mapping_to_structured=None,
               **kwargs):
    '''
    Class contains the Encoder (snapshot -> latent).

    Input:
    ---
    input_size: [int] the number of Nodes in each snapshot.
    dimension: [int] the dimension of the problem, 2 for 2D and 3 for 3D.
    components: [int] the number of components we are compressing.
    structured: [bool] whether the mesh is structured or not.
    self_concat: [int] a channel copying operation, of which the input_channel of the 1D Conv Layers would be components * self_concat
    nearest_neighbouring: [bool] whether the sparse layers are added to the ANN or not.
    sfc_nums: [int] total number of sfcs to use inside the network.
    dims_latent: [int] the dimension of (number of nodes in) the mean-field gaussian latent variable
    activation: [torch.nn.functional] the activation function, ReLU() and Tanh() are usually used.
    variational: [bool] whether this is a variational autoencoder or not.
    coords_option: [int] the option to deal with the float coordinate inputs, default is None (no coordinate input).
    force_initialising_param: [1d-array or 1d-list] a interval to initialize the parameters of the 1D Conv/TransConv, Fully-connected Layers, e.g. [a, b]

    Output:
    ---
    CASE -- (SFC-CAE-Adaptive): 
         x: the compressed latent variable, of shape (batch_size, dims_latent)

    CASE -- (SFC-VCAE-Adaptive):
         x: the compressed latent variable, of shape (batch_size, dims_latent)
         kl_div: the KL-divergence of the latent distribution to a standard Gaussian N(0, 1)
    '''

    super(SFC_CAE_Encoder_Adaptive, self).__init__()
    self.NN = nearest_neighbouring
    self.dims_latent = dims_latent
    self.dimension = dimension
    self.input_size = input_size
    self.components = components
    self.self_concat = self_concat
    self.variational = variational
    self.sfc_nums = sfc_nums
    # self.NN_neighs = []
    self.num_neigh = 3
    # for i in range(self.sfc_nums):self.NN_neighs.append(get_neighbourhood_md(self.orderings[i], gen_neighbour_keys(1), ordering = True))
    self.NN_neigh_1d = get_neighbourhood_md(torch.arange(self.input_size).long(), gen_neighbour_keys(1), ordering = True)
    self.second_sfc = sfc_mapping_to_structured

    if 'num_final_channels' in kwargs.keys():
        self.num_final_channels = kwargs['num_final_channels']
    else: self.num_final_channels = 16  

    if 'direct_neigh' in kwargs.keys():
        self.direct_neigh = kwargs['direct_neigh']
    else: self.direct_neigh = False

    if 'place_center' in kwargs.keys():
        self.place_center = kwargs['place_center']
    else: self.place_center = True

    if 'neighbour_range' in kwargs.keys():
        self.neighbour_range = kwargs['neighbour_range']
    else: self.neighbour_range = 1 

    if 'share_sp_weights' in kwargs.keys():
        self.share_sp_weights = kwargs['share_sp_weights']
    else: self.share_sp_weights = False

    if 'share_conv_weights' in kwargs.keys():
        self.share_conv_weights = kwargs['share_conv_weights']
    else: self.share_conv_weights = False

    if 'collect_loss_inside' in kwargs.keys():
        self.collect_loss_inside = kwargs['collect_loss_inside']
    else: self.collect_loss_inside = False

    if 'interpolate_num' in kwargs.keys():
        self.interpolate_num = kwargs['interpolate_num']
    else: self.interpolate_num = None

    if 'batch_normalisation' in kwargs.keys():
        self.batch_normalisation = kwargs['batch_normalisation']
    else: self.batch_normalisation = False

    if self.interpolate_num is not None: self.input_size = self.interpolate_num

    if 'coords' in kwargs.keys() and kwargs['coords'] is not None:
       self.coords = kwargs['coords']
       self.coords_dim = coords_dimension
       self.components += self.coords_dim
       self.input_channel = self.components * self.self_concat

       if 'ban_shuffle_sp' in kwargs.keys():
          self.ban_shuffle_sp = kwargs['ban_shuffle_sp']
       else: self.ban_shuffle_sp = False

       if 'shuffle_sp_kernel_size' in kwargs.keys():
          self.shuffle_sp_kernel_size = kwargs['shuffle_sp_kernel_size']
          if self.shuffle_sp_kernel_size % 2 == 0:
             raise ValueError("the 'shuffle_sp' layer should have an odd kernel size!!!")
       else: self.shuffle_sp_kernel_size = 31
       self.shuffle_sp_padding = self.shuffle_sp_kernel_size // 2

       if 'shuffle_sp_channel' in kwargs.keys():
           self.shuffle_sp_channel = kwargs['shuffle_sp_channel']
       else: 
           self.shuffle_sp_channel = 32       

       if 'decrease_in_channel' in kwargs.keys() and kwargs['decrease_in_channel'] is True and not self.ban_shuffle_sp and self.NN: 
           self.first_conv_channel = self.shuffle_sp_channel
       else: 
           self.first_conv_channel = None
           if self.NN and not self.ban_shuffle_sp: 
              self.input_channel = self.shuffle_sp_channel
              if self.num_final_channels <= self.input_channel: self.num_final_channels = self.input_channel

       if 'coords_option' in kwargs.keys():
          self.coords_option = kwargs['coords_option']
       else:
          self.coords_option = 1
       
       if 'extract_by_sp' in kwargs.keys():
          self.extract_by_sp = kwargs['extract_by_sp']
       else: self.extract_by_sp = False

    else: 
      self.coords = None
      self.coords_dim = 0
      self.first_conv_channel = None
      self.ban_shuffle_sp = True
      self.input_channel = self.components * self.self_concat

    self.structured = structured

    if self.structured: 
       if activation is None:
          self.activate = nn.ReLU()
       else:
          self.activate = activation     
    else: 
       if activation is None:
          self.activate = nn.Tanh()
       else:
          self.activate = activation

    if  force_initialising_param is not None and len(force_initialising_param) != 2:
      raise ValueError("the input size of 'force_initialising_param' must be 2 !!!")
    else:
      self.init_param = force_initialising_param  

    if sfc_mapping_to_structured is not None:
         self.structured_size_input = self.second_sfc.shape[-1]
         self.diff_nodes = self.structured_size_input - self.input_size
         self.structured_size = np.round(np.power(self.structured_size_input, (1/self.dimension))).astype('int')
         self.shape = (self.structured_size,) * self.dimension
        #  self.num_neigh_md = 3 ** self.dimension

    if sfc_mapping_to_structured is None:
       
      if dimension == 2: 
        self.kernel_size = 32
        self.stride = 4
        self.increase_multi = 2
      elif dimension == 3:
        self.kernel_size = 176
        self.stride = 8
        self.increase_multi = 4

      self.padding = self.kernel_size//2
      self.num_neigh_md = 3
      self.shape = (self.input_size,)

      # find size of convolutional layers and fully-connected layers, see the funtion 'find_size_conv_layers_and_fc_layers()' in utils.py
      self.conv_size, self.size_conv, self.size_fc, self.channels, self.inv_conv_start, self.output_paddings \
      = find_size_conv_layers_and_fc_layers(self.input_size, self.kernel_size, self.padding, self.stride, self.dims_latent, self.sfc_nums, self.input_channel, self.increase_multi,  self.num_final_channels, self.first_conv_channel)
    
    elif sfc_mapping_to_structured is not None: 
         if 'kernel_size' in kwargs.keys():
            self.kernel_size = kwargs['kernel_size']
         else: self.kernel_size = 5

         if 'stride' in kwargs.keys():
                self.stride = kwargs['stride']
         else: self.stride = 2

         if 'padding' in kwargs.keys():
                self.padding = kwargs['padding']
         else: self.padding = 2

         if 'increase_multi' in kwargs.keys():
                self.increase_multi = kwargs['increase_multi']
         else: self.increase_multi = 4     

         # find size of convolutional layers and fully-connected layers, see the funtion 'find_size_conv_layers_and_fc_layers()' in utils.py
         self.conv_size, self.size_conv, self.size_fc, self.channels, self.inv_conv_start, self.output_paddings \
         = find_size_conv_layers_and_fc_layers(self.structured_size, self.kernel_size, self.padding, self.stride, self.dims_latent, self.sfc_nums, self.input_channel, self.increase_multi,  self.num_final_channels, self.first_conv_channel, self.dimension)
         
         self.Ax = gen_neighbour_keys(ndim=self.dimension, range=self.neighbour_range, direct_neigh=self.direct_neigh)
        #  self.neigh_md = get_neighbourhood_md(self.second_sfc.reshape(self.shape), self.Ax, ordering = True)
         self.num_neigh_md = len(self.Ax) + 1
         self.neigh_md = get_neighbourhood_md((torch.arange(self.structured_size_input).long()).reshape(self.shape), self.Ax, ordering = True)

         # parameters for expand snapshots
         self.filling_layer = BackwardForwardConnecting(self.input_size, self.structured_size_input)
         # self.expand_paras = gen_filling_paras(self.input_size, self.structured_size_input)

    # set up convolutional layers, fully-connected layers and sparse layers
    self.fcs = []
    self.convs = []

    if self.coords is not None:
        self.coords_channels = []
        for i in range(len(self.channels)): 
            self.coords_channels.append(int(self.channels[i] * self.coords_dim / self.components))
    
    if not self.share_conv_weights:
      for i in range(self.sfc_nums):
       self.convs.append([])
       for j in range(self.size_conv):
           in_channels = self.channels[j]
           if self.coords is not None and self.coords_option == 2: in_channels += self.coords_channels[j]
           out_channels = self.channels[j+1]
           if sfc_mapping_to_structured is None: 
              self.convs[i].append(nn.Conv1d(in_channels, out_channels, kernel_size=self.kernel_size, stride=self.stride, padding=self.padding))
           else:
              if self.dimension == 2:
                  self.convs[i].append(nn.Conv2d(in_channels, out_channels, kernel_size=self.kernel_size, stride=self.stride, padding=self.padding))
              elif self.dimension == 3:
                  self.convs[i].append(nn.Conv3d(in_channels, out_channels, kernel_size=self.kernel_size, stride=self.stride, padding=self.padding))
           if self.init_param is not None: 
              self.convs[i][j].weight.data.uniform_(self.init_param[0], self.init_param[1])
              self.convs[i][j].bias.data.fill_(0.001)
       self.convs[i] = nn.ModuleList(self.convs[i])
    else:
       for i in range(self.size_conv):
           in_channels = self.channels[i]
           if self.coords is not None and self.coords_option == 2: in_channels += self.coords_channels[i]
           out_channels = self.channels[i+1]
           if sfc_mapping_to_structured is None: 
              self.convs.append(nn.Conv1d(in_channels, out_channels, kernel_size=self.kernel_size, stride=self.stride, padding=self.padding))
           else:
              if self.dimension == 2:
                  self.convs.append(nn.Conv2d(in_channels, out_channels, kernel_size=self.kernel_size, stride=self.stride, padding=self.padding))
              elif self.dimension == 3:
                  self.convs.append(nn.Conv3d(in_channels, out_channels, kernel_size=self.kernel_size, stride=self.stride, padding=self.padding))
           if self.init_param is not None: 
              self.convs[i].weight.data.uniform_(self.init_param[0], self.init_param[1])
              self.convs[i].bias.data.fill_(0.001)       

    self.convs = nn.ModuleList(self.convs)

    if self.NN:
      if not self.share_sp_weights: 
        self.sps = []
        for i in range(self.sfc_nums):          
        #   if sfc_mapping_to_structured is None:
        #     self.sps.append(NearestNeighbouring(size = self.input_size * self.input_channel, initial_weight= (1/3), num_neigh = 3))
        #   else:
          if self.coords is not None and not self.ban_shuffle_sp: 
             self.sps.append(nn.Conv1d(self.components * self.self_concat, self.shuffle_sp_channel, self.shuffle_sp_kernel_size, 1, self.shuffle_sp_padding))
            #  self.sps[i].weight.data.fill_(1)
            #  self.sps[i].bias.data.fill_(0)
          else: self.sps.append(NearestNeighbouring_md(shape = self.shape, initial_weight= None, channels = self.components * self.self_concat, num_neigh_md = self.num_neigh_md)) 
      else: 
        if self.coords is not None and not self.ban_shuffle_sp: 
           self.sps = nn.Conv1d(self.components * self.self_concat, self.shuffle_sp_channel, self.shuffle_sp_kernel_size, 1, self.shuffle_sp_padding)
         #   self.sps.weight.data.fill_(1)
         #   self.sps.bias.data.fill_(0)
        else: self.sps = NearestNeighbouring_md(shape = self.shape, initial_weight= None, channels = self.components * self.self_concat, num_neigh_md = self.num_neigh_md)

    if self.NN and not self.share_sp_weights: self.sps = nn.ModuleList(self.sps)
    for i in range(len(self.size_fc) - 2):
       self.fcs.append(nn.Linear(self.size_fc[i], self.size_fc[i+1]))
       if self.init_param is not None: 
            self.fcs[i].weight.data.uniform_(self.init_param[0], self.init_param[1])
            self.fcs[i].bias.data.fill_(0.001)

    if self.batch_normalisation:
       self.batch_norm = torch.nn.BatchNorm1d(self.components)
    
    if self.variational:
       self.layerMu = nn.Linear(self.size_fc[-2], self.size_fc[-1])
       self.layerSig = nn.Linear(self.size_fc[-2], self.size_fc[-1])
       self.Normal01 = torch.distributions.Normal(0, 1)
       if self.init_param is not None: 
            self.layerMu.weight.data.uniform_(self.init_param[0], self.init_param[1])
            self.layerMu.bias.data.fill_(0.001)
            self.layerSig.weight.data.uniform_(self.init_param[0], self.init_param[1])
            self.layerSig.bias.data.fill_(0.001)
    else:
       self.fcs.append(nn.Linear(self.size_fc[-2], self.size_fc[-1]))
       if self.init_param is not None: 
            self.fcs[-1].weight.data.uniform_(self.init_param[0], self.init_param[1])
            self.fcs[-1].bias.data.fill_(0.001)
    self.fcs = nn.ModuleList(self.fcs)

  def build_coarsened_coords(self, ordered_coords):
       self.ctoa = []
       if not self.share_conv_weights:
          for i in range(self.sfc_nums):
             for j in range(len(self.conv_size)):
                if j == 0: self.ctoa.append(ordered_coords)   
                else: self.ctoa.append(sparsify(ordered_coords, self.conv_size[j]))
       else:
          for i in range(len(self.conv_size)):
              if i == 0: self.ctoa.append(ordered_coords)   
              else: self.ctoa.append(sparsify(ordered_coords, self.conv_size[i]))  

  def forward(self, x, sfcs, filling_paras, coords=None, sfc_shuffle_index=None):
    '''
    x: [list of torch tensors] the adaptive fluid data snapshot, could have multiple components.
    sfcs: [list of sfc orderings] batch of sfc orderings for the adaptive data.
    filling_paras: [list of 'fla' tuples] a list of indexes for filling the paddings, see 'expand_snapshot_backward_connect()' in utils.py.
    coords: [list of torch tensors] the coordinate inputs, could be empty.
    sfc_shuffle_index: [numpy.ndarray] an index to shuffle, default is None (not shuffle).
    '''

    xs = []
    if self.collect_loss_inside: self.a_s = []
    self.device = x[0].device

    # 1D or MD Conv Layers
    for i in range(self.sfc_nums):
        a = []
        if coords is not None: 
           cds = []
         #   cds = copy.deepcopy(coords)
        for k, (sfc, fla) in enumerate(zip(sfcs, filling_paras)):
            if sfc_shuffle_index is not None: sfc_index = sfc_shuffle_index[i]
            else: sfc_index = i
            a.append(x[k].clone()[..., sfc[sfc_index]])
            if coords is not None:
                   cds.append(coords[k].clone()[..., sfc[sfc_index]])            
            if fla is not None: 
               if self.interpolate_num is None: 
                  # a[k] = expand_snapshot_backward_connect(a[k], *fla, self.place_center)
                  a[k] = fla[0](a[k])
               else: a[k] = linear_interpolate_python(a[k], *fla[0])
               if coords is not None:                  
                 if self.interpolate_num is None: 
                  # cds[k] = expand_snapshot_backward_connect(cds[k], *fla, self.place_center)
                    cds[k] = fla[0](cds[k])
                 else: 
                    cds[k] = linear_interpolate_python(cds[k], *fla[0])
        if coords is not None:
            cds = torch.stack(cds)
            if self.coords_option == 2: self.build_coarsened_coords(cds)
        a = torch.stack(a)
        if self.collect_loss_inside: self.a_s.append(a)
        if coords is not None: a = torch.cat((a, cds), 1)
        if self.batch_normalisation: a = self.batch_norm(a)
        # print(a.shape)
        if self.self_concat > 1: 
           if a.ndim == 2: a = a.unsqueeze(1)
           a = torch.cat([a] * self.self_concat, 1)  
        # print(a.shape)      
        if self.second_sfc is not None: 
            # a = expand_snapshot_backward_connect(a, *self.expand_paras, place_center = self.place_center)
            a = self.filling_layer(a)
            # print(a.shape)
            a = a[..., self.second_sfc]
            if self.NN:
               tt_list = get_concat_list_md(a, self.neigh_md, self.num_neigh_md)
            #    print(tt_list.shape)
               if not self.share_sp_weights: tt_nn = self.sps[i](tt_list)
               else: tt_nn = self.sps(tt_list)
               a = self.activate(tt_nn)
               del tt_list
               del tt_nn
            a = a.reshape(a.shape[:-1] + self.shape)
        else: 
            if self.NN:
               if self.coords is not None and not self.ban_shuffle_sp: tt_list = a
               else: tt_list = get_concat_list_md(a, self.NN_neigh_1d, self.num_neigh)
               if not self.share_sp_weights: tt_nn = self.sps[i](tt_list)
               else: tt_nn = self.sps(tt_list)
               a = self.activate(tt_nn)
               del tt_list
               del tt_nn   
            # a = a.reshape((a.shape[0], self.input_channel, self.input_size)) 
        # if self.input_channel > 1: a = a.view(-1, self.input_channel, self.input_size)
        # else: a = a.unsqueeze(1)
        if self.share_conv_weights: conv_layer = self.convs
        else: conv_layer = self.convs[i]
        for j in range(self.size_conv):
            if self.coords is not None and self.coords_option == 2: 
               # we feed the coarsened coords in each conv layer
               a = torch.cat((a, self.ctoa[j].repeat(1, self.coords_channels[j] // self.coords_dim,1).to(a.device)),1)
            a = self.activate(conv_layer[j](a))
        # xs.append(a.view(-1, a.size(1)*a.size(2)))
      #   a = a.reshape(a.shape[0], -1)
        a = a.view(-1, np.prod(a.shape[1:]))
        xs.append(a)
        # print(a.shape)
        del a
    del x
    if self.sfc_nums > 1: x = torch.cat(xs, 1)
    else: x = xs[0]
    # x = x.reshape(x.shape[0], -1)
    for i in range(self.sfc_nums): del xs[0] # clear memory 

    # fully connect layers
    for i in range(len(self.fcs)): x = self.activate(self.fcs[i](x))

    # variational sampling
    if self.variational:
      mu = self.layerMu(x)
      sigma = torch.exp(self.layerSig(x))
      sample = self.Normal01.sample(mu.shape).to(x.device)
      x = mu + sigma * sample
      kl_div = ((sigma**2 + mu**2 - torch.log(sigma) - 1/2).sum()) / (mu.shape[0] * self.input_size * self.components)
      return x, kl_div
    else: return x


###############################################################   Decoder Part ###################################################################

class SFC_CAE_Decoder_Adaptive(nn.Module): 
  def __init__(self, encoder, output_linear = False, reduce_strategy = 'truncate'):
    '''
    Class contains the Decoder for SFC_CAE (latent -> reconstructed snapshot).

    Input:
    ---
    encoder: [SFC_CAE_Encoder object] the SFC_CAE_Encoder class, we want to nearly 'invert' the operation, so we just inherit most parameters from the Encoder.
    output_linear: [bool] default is false, if turned on, a linear activation will be applied at the output.

    Output:
    ---
    CASE -- (SFC-CAE-md): 
         z: the reconstructed batch of snapshots, in 1D, of shape (batch_size, number of Nodes, number of components)

    CASE -- (SFC-VCAE-md):
         z: the reconstructed batch of snapshots, in 1D, of shape (batch_size, number of Nodes, number of components)
         kl_div: the KL-divergence of the latent distribution to a standard Gaussian N(0, 1)
    '''

    super(SFC_CAE_Decoder_Adaptive, self).__init__()

    # pass parameters from the encoder
    self.encoder = encoder

    self.NN = encoder.NN
    self.variational = encoder.variational
    self.activate = encoder.activate
    self.dims_latent = encoder.dims_latent
    self.dimension = encoder.dimension
    self.kernel_size = encoder.kernel_size
    self.stride = encoder.stride
    self.padding = encoder.padding
    self.increase_multi = encoder.increase_multi
    self.input_size = encoder.input_size
    self.components = encoder.components
    self.self_concat = encoder.self_concat
    self.num_final_channels = encoder.num_final_channels
    self.output_linear = output_linear
    self.size_conv = encoder.size_conv
    self.inv_conv_start = encoder.inv_conv_start
    self.input_channel = self.components * self.self_concat
    self.sfc_nums = encoder.sfc_nums
    self.shape = encoder.shape

    self.collect_loss_inside = encoder.collect_loss_inside
    self.interpolate_num = encoder.interpolate_num
    self.batch_normalisation = encoder.batch_normalisation

    if encoder.coords is not None:
      self.coords = encoder.coords
      self.coords_dim = encoder.coords_dim
      self.coords_option = encoder.coords_option
      self.ban_shuffle_sp = encoder.ban_shuffle_sp
      self.shuffle_sp_kernel_size = encoder.shuffle_sp_kernel_size
      self.shuffle_sp_padding = encoder.shuffle_sp_padding
      self.shuffle_sp_channel = encoder.shuffle_sp_channel
      self.coords_channels = encoder.coords_channels
      self.extract_by_sp = encoder.extract_by_sp
    
    self.neighbour_range = encoder.neighbour_range
    self.place_center = encoder.place_center
    self.reduce = reduce_strategy

    # inherit weight sharing from encoder
    self.share_sp_weights = encoder.share_sp_weights
    self.share_conv_weights = encoder.share_conv_weights

    # self.NN_neighs = []
    self.num_neigh = encoder.num_neigh
    # for i in range(self.sfc_nums):self.NN_neighs.append(get_neighbourhood_md(self.orderings[i], gen_neighbour_keys(1), ordering = True))
    self.NN_neigh_1d = encoder.NN_neigh_1d

    # md Decoder
    if encoder.second_sfc is None: 
        self.inv_second_sfc = None
        self.init_convTrans_shape = (encoder.num_final_channels, ) + (encoder.conv_size[-1], )
        self.num_neigh_md = encoder.num_neigh_md 
    else: 
        self.inv_second_sfc = np.argsort(encoder.second_sfc)  
        self.structured_size_input = self.inv_second_sfc.shape[-1]
        self.diff_nodes = encoder.diff_nodes
        self.structured_size = encoder.structured_size
        self.shape = encoder.shape
        self.num_neigh_md = encoder.num_neigh_md   
        self.neigh_md = encoder.neigh_md   
        self.init_convTrans_shape = (encoder.num_final_channels, ) + (encoder.conv_size[-1], ) * self.dimension
        # self.expand_paras = encoder.expand_paras
        self.expand_extract_layer = BackwardForwardConnecting(self.structured_size_input, self.input_size)
    self.fcs = []
    # set up fully-connected layers
    for k in range(1, len(encoder.size_fc)):
       self.fcs.append(nn.Linear(encoder.size_fc[-k], encoder.size_fc[-k-1]))
       if encoder.init_param is not None: 
            self.fcs[k - 1].weight.data.uniform_(encoder.init_param[0], encoder.init_param[1])
            self.fcs[k - 1].bias.data.fill_(0.001) 
    self.fcs = nn.ModuleList(self.fcs)

    # set up convolutional layers, fully-connected layers and sparse layers
    self.convTrans = []
    self.sps = []
    if not self.share_conv_weights:
      for i in range(self.sfc_nums):
        self.convTrans.append([])
        for j in range(1, encoder.size_conv + 1):
           in_channels = encoder.channels[-j]
           if self.coords is not None and self.coords_option == 2: in_channels += self.coords_channels[-j]
           out_channels = encoder.channels[-j-1]
           if encoder.second_sfc is None:
              self.convTrans[i].append(nn.ConvTranspose1d(in_channels, out_channels, kernel_size=self.kernel_size, stride=self.stride, padding=encoder.padding, output_padding = encoder.output_paddings[j - 1]))
           else:
              if self.dimension == 2:
                  self.convTrans[i].append(nn.ConvTranspose2d(in_channels, out_channels, kernel_size=self.kernel_size, stride=self.stride, padding=encoder.padding, output_padding = encoder.output_paddings[j - 1]))
              elif self.dimension == 3:
                  self.convTrans[i].append(nn.ConvTranspose3d(in_channels, out_channels, kernel_size=self.kernel_size, stride=self.stride, padding=encoder.padding, output_padding = encoder.output_paddings[j - 1]))               
           if encoder.init_param is not None: 
              self.convTrans[i][j - 1].weight.data.uniform_(encoder.init_param[0], encoder.init_param[1])
              self.convTrans[i][j - 1].bias.data.fill_(0.001)       
        self.convTrans[i] = nn.ModuleList(self.convTrans[i])
    else:
        for i in range(1, encoder.size_conv + 1):
            in_channels = encoder.channels[-i]
            if self.coords is not None and self.coords_option == 2: in_channels += self.coords_channels[-i]
            out_channels = encoder.channels[-i-1]              
            if encoder.second_sfc is None:
              self.convTrans.append(nn.ConvTranspose1d(in_channels, out_channels, kernel_size=self.kernel_size, stride=self.stride, padding=encoder.padding, output_padding = encoder.output_paddings[i - 1]))
            else:
              if self.dimension == 2:
                  self.convTrans.append(nn.ConvTranspose2d(in_channels, out_channels, kernel_size=self.kernel_size, stride=self.stride, padding=encoder.padding, output_padding = encoder.output_paddings[i - 1]))
              elif self.dimension == 3:
                  self.convTrans.append(nn.ConvTranspose3d(in_channels, out_channels, kernel_size=self.kernel_size, stride=self.stride, padding=encoder.padding, output_padding = encoder.output_paddings[i - 1]))               
            if encoder.init_param is not None: 
              self.convTrans[i - 1].weight.data.uniform_(encoder.init_param[0], encoder.init_param[1])
              self.convTrans[i - 1].bias.data.fill_(0.001)       
  
    if self.NN:
       if self.coords is not None and self.extract_by_sp: 
          out_channel = self.components - self.coords_dim
          concats = self.self_concat * self.coords_dim
       else: 
          out_channel = self.components
          concats = self.self_concat

       if not self.share_sp_weights:
          for i in range(self.sfc_nums):
        #   if encoder.second_sfc is None:
        #     self.sps.append(NearestNeighbouring(size = self.input_size * self.input_channel, initial_weight= (1/3), num_neigh = 3))
        #   else:
            if self.coords is not None and not self.ban_shuffle_sp:
                  self.sps.append(nn.ConvTranspose1d(self.shuffle_sp_channel, out_channel, self.shuffle_sp_kernel_size, 1, self.shuffle_sp_padding))
                  # self.sps[i].weight.data.fill_(1)
                  # self.sps[i].bias.data.fill_(0)
            else: self.sps.append(NearestNeighbouring_md(self.shape, None, out_channel, self.num_neigh_md, concats)) 
       else:
          if self.coords is not None and not self.ban_shuffle_sp: 
             self.sps = nn.ConvTranspose1d(self.shuffle_sp_channel, out_channel, self.shuffle_sp_kernel_size, 1, self.shuffle_sp_padding)
            #  self.sps.weight.data.fill_(1)
            #  self.sps.bias.data.fill_(0)
          else: self.sps = NearestNeighbouring_md(self.shape, None, out_channel, self.num_neigh_md, concats)

    self.convTrans = nn.ModuleList(self.convTrans)
    if self.NN: 
       if not self.share_sp_weights: self.sps = nn.ModuleList(self.sps) 
       else: self.sps = nn.Sequential(self.sps)[0]        

    self.split = encoder.size_fc[0] // self.sfc_nums

    # final sparse layer combining SFC outputs, those two approaches are not as good as the simple [tensor_list].sum(-1)
    # if self.sfc_nums > 1: self.final_sp = nn.Parameter(torch.ones(self.sfc_nums) / self.sfc_nums)
    # if self.sfc_nums > 1: self.final_sp = NearestNeighbouring(size = self.input_size * self.components, initial_weight= 1 / self.sfc_nums, num_neigh = self.sfc_nums)

    # final linear activate (shut down it if you have standardlized your data first)
   #  if output_linear:
   #    self.out_linear_weights = []
   #    self.out_linear_bias = []
   #    for i in range(self.components):
   #        self.out_linear_weights.append(nn.Parameter(torch.ones(self.input_size)))
   #        self.out_linear_bias.append(nn.Parameter(torch.zeros(self.input_size)))
   #    self.out_linear_weights = nn.ModuleList(self.out_linear_weights)
   #    self.out_linear_bias = nn.ModuleList(self.out_linear_bias)
    if output_linear:
      self.out_linear_weights = nn.Parameter(torch.ones(self.components))
      self.out_linear_bias = nn.Parameter(torch.zeros(self.components))

  def forward(self, x, inv_sfcs, filling_paras, coords=None, sfc_shuffle_index=None):
    '''
    x: [list of torch tensors] the adaptive fluid data snapshot, could have multiple components.
    sfcs: [list of sfc orderings] batch of sfc orderings for the adaptive data.
    filling_paras: [list of 'fla' tuples] a list of indexes for filling the paddings, see 'expand_snapshot_backward_connect()' in utils.py.
    coords: [list of torch tensors] the coordinate inputs, could be empty.
    sfc_shuffle_index: [numpy.ndarray] an index to shuffle, default is None (not shuffle).
    ''' 

    for i in range(len(self.fcs)):
        x = self.activate(self.fcs[i](x))
    # revert torch.cat
    if self.sfc_nums > 1: x = torch.chunk(x, chunks=self.sfc_nums, dim=1)
    else: x = (x,)

    # collect loss inside
    if self.collect_loss_inside: self.loss = 0

    for i in range(self.sfc_nums):
        # if self.inv_second_sfc is not None: 
      #   b = x[i].reshape((x[i].shape[0],) + self.init_convTrans_shape)
        b = x[i].view((-1,) + self.init_convTrans_shape)
        if self.share_conv_weights: conv_layer = self.convTrans
        else: conv_layer = self.convTrans[i]
        if self.coords is not None and self.coords_option == 2: self.ctoa = self.encoder.ctoa
        for j in range(self.size_conv):
            if self.coords is not None and self.coords_option == 2: 
               # we feed the coarsened coords in each conv layer
               b = torch.cat((b, self.ctoa[-j-1].repeat(1, self.coords_channels[-j-1] // self.coords_dim,1).to(b.device)),1)
            b = self.activate(conv_layer[j](b))
        if self.inv_second_sfc is not None: 
            b = b.reshape(b.shape[:2] + (self.structured_size_input, ))
            # b = b[..., self.inv_second_sfc]
            if self.NN:
              #  print('before decoder concat..')
              #  print(b.shape)
               if self.coords is not None and not self.ban_shuffle_sp: tt_list = b
               else: tt_list = get_concat_list_md(b, self.neigh_md, self.num_neigh_md, self.self_concat)
              #  print(tt_list.shape)
               if not self.share_sp_weights: tt_nn = self.sps[i](tt_list)
               else: tt_nn = self.sps(tt_list)
               b = self.activate(tt_nn)
               del tt_list 
               del tt_nn  
            else:
               if self.self_concat > 1: b = sum(torch.chunk(b, chunks=self.self_concat, dim=1))
            b = b[..., self.inv_second_sfc]
            # b = reduce_expanded_snapshot(b, *self.expand_paras, self.place_center, self.reduce) # truncate or mean
            b = self.expand_extract_layer(b)
            # print(b.shape)       
        else: 
            # b = b[..., self.orderings[i]] # backward order refer to first sfc(s).
            # b = b.reshape(b.shape[:2] + (self.input_size, ))
            if self.NN:
               if self.coords is not None and not self.ban_shuffle_sp: tt_list = b
               else: 
                 if self.extract_by_sp: concats = self.self_concat * self.coords_dim
                 else: concats = self.self_concat
                 tt_list = get_concat_list_md(b, self.NN_neigh_1d, self.num_neigh, concats)
               if not self.share_sp_weights: tt_nn = self.sps[i](tt_list)
               else: tt_nn = self.sps(tt_list)
               b = self.activate(tt_nn)
               del tt_list
               del tt_nn
            else: 
              if self.self_concat > 1: b = sum(torch.chunk(b, chunks=self.self_concat, dim=1))

        if not self.extract_by_sp: b = b[:, :self.components - self.coords_dim]
        
        if self.collect_loss_inside:  
           self.loss += nn.MSELoss()(b, self.encoder.a_s[i])
        # print(b.shape)
  
        b = list(b)
        if self.coords_dim is not None: coords_b_list = []
        for k, (inv_sfc, fla) in enumerate(zip(inv_sfcs, filling_paras)):
            if sfc_shuffle_index is not None: sfc_index = sfc_shuffle_index[i]
            else: sfc_index = i
            if fla is not None: 
               if self.interpolate_num is None: 
                  # b[k] = reduce_expanded_snapshot(b[k], *fla, self.place_center, self.reduce)
                  b[k] = fla[1](b[k])
               else: 
                  b[k] = linear_interpolate_python(b[k], *fla[-1])
            b[k] = b[k][..., inv_sfc[sfc_index]].squeeze(0)
            # if self.coords_dim is not None: 
            #    coords_b_list.append(b[k][-self.coords_dim:])
            #    if not self.extract_by_sp: b[k] = b[k][:self.components - self.coords_dim].unsqueeze(-1)
            #    else: b[k] = b[k].unsqueeze(-1)
            b[k] = b[k].unsqueeze(-1)
              #  print('b[k] shape:', b[k].shape)
        if i == 0: 
           data_z = []
           for k in range(len(b)): 
            data_z.append(b[k].clone())
        else: 
            for k in range(len(b)): 
              data_z[k] = torch.cat((data_z[k], b[k]), dim=-1)      
              # print('z[k] shape:', data_z[k].shape)   
    # if self.inv_second_sfc is not None: return z[..., :self.input_size]
    # else: 
    for i in range(len(data_z)): 
        data_z[i] = self.activate(data_z[i].sum(-1))
        # data_z[i] = self.activate(data_z[i])
    return data_z


###############################################################   AutoEncoder Wrapper ###################################################################
class SFC_CAE_Adaptive(nn.Module):
  def __init__(self, 
               input_size,
               dimension,
               components,
               structured,
               self_concat,
               nearest_neighbouring, 
               dims_latent, 
               sfc_nums,
               activation,
               variational,
               coords_dimension,
               force_initialising_param=None,
               sfc_mapping_to_structured=None,
               output_linear = False,
               reduce_strategy = 'truncate',
               **kwargs):
    '''
    SFC_CAE Class combines the SFC_CAE_Encoder and the SFC_CAE_Decoder with an Autoencoder latent space.

    Input:
    ---
    size: [int] the number of Nodes in each snapshot.
    dimension: [int] the dimension of the problem, 2 for 2D and 3 for 3D.
    components: [int] the number of components we are compressing.
    structured: [bool] whether the mesh is structured or not.
    self_concat: [int] a channel copying operation, of which the input_channel of the 1D Conv Layers would be components * self_concat
    nearest_neighbouring: [bool] whether the sparse layers are added to the ANN or not.
    dims_latent: [int] the dimension of (number of nodes in) the mean-field gaussian latent variable
    space_filling_orderings: [list of 1D-arrays] the space-filling curves, of shape [number of curves, number of Nodes]
    invert_space_filling_orderings: [list of 1D-arrays] the inverse space-filling curves, of shape [number of curves, number of Nodes]
    activation: [torch.nn.functional] the activation function, ReLU() and Tanh() are usually used.
    variational: [bool] whether this is a variational autoencoder or not.
    force_initialising_param: [1d-array or 1d-list] a interval to initialize the parameters of the 1D Conv/TransConv, Fully-connected Layers, e.g. [a, b]
    output_linear: [bool] default is false, if turned on, a linear activation will be applied at the output.

    Output:
    ---
    CASE -- (SFC-CAE-Adaptive): 
         self.decoder(z): the reconstructed batch of snapshots, in 1D, of shape (batch_size, number of Nodes, number of components)

    CASE -- (SFC-VCAE-Adaptive):
         self.decoder(z): the reconstructed batch of snapshots, in 1D, of shape (batch_size, number of Nodes, number of components)
         kl_div: the KL-divergence of the latent distribution to a standard Gaussian N(0, 1)
    '''

    super(SFC_CAE_Adaptive, self).__init__()
    self.encoder = SFC_CAE_Encoder_Adaptive(input_size,
               dimension,
               components,
               structured,
               self_concat,
               nearest_neighbouring, 
               dims_latent, 
               sfc_nums,
               activation,
               variational,
               coords_dimension,
               force_initialising_param,
               sfc_mapping_to_structured,
               **kwargs)
    self.decoder = SFC_CAE_Decoder_Adaptive(self.encoder, output_linear, reduce_strategy)
   
    # specify name of the activation
    if isinstance(self.encoder.activate, type(nn.ReLU())):
      self.activate = 'ReLU'
    elif isinstance(self.encoder.activate, type(nn.Tanh())):
      self.activate = 'Tanh'
    elif isinstance(self.encoder.activate, type(nn.SELU())):
      self.activate = 'SELU'

  def forward(self, x, sfcs, inv_sfcs, filling_paras, coords=None, sfc_shuffle_index=None):
   '''
   x - [Torch.Tensor.float] A batch of fluid snapshots from the data-loader
   '''
   # return value for VAE 
   if self.encoder.variational:
      z, kl_div = self.encoder(x, sfcs, filling_paras, coords, sfc_shuffle_index) # encoder, compress each image to 1-D data of size {dims_latent}, as well as record the KL divergence.
      return self.decoder(z, inv_sfcs, filling_paras, coords, sfc_shuffle_index), kl_div
   # return value for normal AE
   else:
      z = self.encoder(x, sfcs, filling_paras, coords, sfc_shuffle_index) # encoder, compress each image to 1-D data of size {dims_latent}.
      return self.decoder(z, inv_sfcs, filling_paras, coords, sfc_shuffle_index)  # Return the output of the decoder (1-D, the predicted image)


