"""A simulated experiment model used by the sckript fit.py

Model name: m3b
Definition:
    group index j = 1 ... J
    input index d = 1 ... D
    explanatory variable x = [x_1 ... x_D]
    response variable y
    local parameter alpha = [alpha_1 ... alpha_J]
    local parameter beta = [[beta_11 ... beta_1D] ... [beta_J1 ... beta_JD]]
    shared parameter sigma_a
    shared parameter sigma_b = [sigma_b_1 ... sigma_b_D]
    y ~ bernoulli_logit(alpha_j + beta_j*' * x)
    alpha ~ N(0, sigma_a)
    beta_*d ~ N(0, sigma_b_d), for all d
    sigma_a ~ log-N(0, sigma_aH)
    sigma_b_d ~ log-N(0, sigma_bH), for all d
    phi = [log(sigma_a), log(sigma_b)]

"""

# Licensed under the 3-clause BSD license.
# http://opensource.org/licenses/BSD-3-Clause
#
# Copyright (C) 2014 Tuomas Sivula
# All rights reserved.

from __future__ import division
import numpy as np
from scipy.linalg import cholesky
from common import data, calc_input_param_classification, rand_corr_vine


# ------------------------------------------------------------------------------
# >>>>>>>>>>>>> Configurations start >>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>
# ------------------------------------------------------------------------------

# ====== Model parameters ======================================================
# If SIGMA_A is None, it is sampled from log-N(0,SIGMA_AH)
SIGMA_A = 1
SIGMA_AH = None
SIGMA_BH = 1

# ====== Prior =================================================================
# Prior for log(sigma_a)
M0_A = 0
V0_A = 1.5**2
# Prior for log(sigma_b)
M0_B = 0
V0_B = 1.5**2

# ====== Regulation ============================================================
# Min for abs(sum(beta))
B_ABS_MIN_SUM = 1e-4

# ------------------------------------------------------------------------------
# <<<<<<<<<<<<< Configurations end <<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<
# ------------------------------------------------------------------------------


class model(object):
    """Model definition.
    
    Parameters
    ----------
    J : int
        Number of groups
    
    D : int
        Number of inputs
    
    npg : {int, seq of ints}
        Number of observations per group (constant or [min, max])
    
    """
    
    def __init__(self, J, D, npg):
        self.J = J
        self.D = D
        self.npg = npg
        self.dphi = D+1
    
    def simulate_data(self, Sigma_x=None, seed=None):
        """Simulate data from the model.
        
        Returns models.common.data instance
        
        Parameters
        ----------
        Sigma_x : {None, 'rand', ndarray}
            The covariance structure of the explanatory variable. This is 
            scaled to regulate the uncertainty. If not provided or None, 
            identity matrix is used. Providing string 'rand' uses method
            common.rand_corr_vine to randomise one.
        
        """
        # Localise params
        J = self.J
        D = self.D
        npg = self.npg
        
        # Set seed
        rnd_data = np.random.RandomState(seed=seed)
        
        # Randomise input covariance structure if needed
        if Sigma_x == 'rand':
            Sigma_x = rand_corr_vine(D, seed=rnd_data)
        
        # Parameters
        # Number of observations for each group
        if hasattr(npg, '__getitem__') and len(npg) == 2:
            Nj = rnd_data.randint(npg[0],npg[1]+1, size=J)
        else:
            Nj = npg*np.ones(J, dtype=np.int64)
        # Total number of observations
        N = np.sum(Nj)
        # Observation index limits for J groups
        j_lim = np.concatenate(([0], np.cumsum(Nj)))
        # Group indices for each sample
        j_ind = np.empty(N, dtype=np.int64)
        for j in xrange(J):
            j_ind[j_lim[j]:j_lim[j+1]] = j
        
        # Assign parameters
        if SIGMA_A is None:
            sigma_a = np.exp(rnd_data.randn()*SIGMA_AH)
        else:
            sigma_a = SIGMA_A
        sigma_b = np.exp(rnd_data.randn(D)*SIGMA_BH)
        alpha_j = rnd_data.randn(J)*sigma_a
        beta_j = rnd_data.randn(J,D)*sigma_b
        
        # Regulate beta
        for j in xrange(J):
            beta_sum = np.sum(beta_j[j])
            while np.abs(beta_sum) < B_ABS_MIN_SUM:
                # Replace one random element in beta
                index = rnd_data.randint(D)
                beta_sum -= beta_j[j,index]
                beta_j[j,index] = rnd_data.randn()*sigma_b[index]
                beta_sum += beta_j[j,index]
        
        phi_true = np.append(np.log(sigma_a), np.log(sigma_b))
        
        # Determine suitable mu_x and sigma_x
        mu_x_j, sigma_x_j = calc_input_param_classification(
            alpha_j, beta_j, Sigma_x
        )
        
        # Simulate data
        # Different mu_x and sigma_x for every group
        X = np.empty((N,D))
        if Sigma_x is None:
            for j in xrange(J):
                X[j_lim[j]:j_lim[j+1],:] = \
                    mu_x_j[j] + rnd_data.randn(Nj[j],D)*sigma_x_j[j]
        else:
            cho_x = cholesky(Sigma_x)
            for j in xrange(J):
                X[j_lim[j]:j_lim[j+1],:] = \
                    mu_x_j[j] + rnd_data.randn(Nj[j],D).dot(sigma_x_j[j]*cho_x)
        y = np.empty(N)
        for n in xrange(N):
            y[n] = alpha_j[j_ind[n]] + X[n].dot(beta_j[j_ind[n]])
        y = 1/(1+np.exp(-y))
        y_true = (0.5 < y).astype(int)
        y = (rnd_data.rand(N) < y).astype(int)
        
        return data(
            X, y, {'mu_x':mu_x_j, 'sigma_x':sigma_x_j, 'Sigma_x':Sigma_x}, 
            y_true, Nj, j_lim, j_ind, {'phi':phi_true, 'alpha':alpha_j, 
            'beta':beta_j}
        )
    
    def get_prior(self):
        """Get prior for the model.
        
        Returns: S, m, Q, r
        
        """
        D = self.D
        # Moment parameters of the prior (transposed in order to get
        # F-contiguous)
        S0 = np.diag(np.append(V0_A, np.ones(D)*V0_B)).T
        m0 = np.append(M0_A, np.ones(D)*M0_B)
        # Natural parameters of the prior
        Q0 = np.diag(np.append(1./V0_A, np.ones(D)/V0_B)).T
        r0 = np.append(M0_A/V0_A, np.ones(D)*(M0_B/V0_B))
        return S0, m0, Q0, r0
    
    def get_param_definitions(self):
        """Return the definition of the inferred parameters.
        
        Returns
        -------
        names : seq of str
            Names of the parameters
        
        shapes : seq of tuples
            Shapes of the parameters
        
        hiers : seq of int 
            The indexes of the hierarchical dimension of the parameter or None
            if it does not have one.
        
        """
        names = ('alpha', 'beta')
        shapes = ((self.J,), (self.J,self.D))
        hiers = (0, 0)
        return names, shapes, hiers


