# -*- coding: utf-8 -*-
"""
DEFINES:

1) A wrapper that iterates over calc_rho.py
Calculates rho(z,r) on a grid of values defined by z, r, assuming vertical
hydrostatic equilibrium and an isothermal equation of state.

2) The rho class

3) Calculation of the CDF inverse of rho

Created on Mon Jan 27 15:06:44 2014

@author: ibackus
"""

# ICgen packages
import calc_rho
import isaac

# External packages
import copy as copier
import numpy as np
import time
import cPickle as pickle
import scipy.interpolate as interp

import pynbody
SimArray = pynbody.array.SimArray


def rho_zr(ICobj):
    """
    Iterates over calc_rho.py to calculate rho(z,r) on a grid of z and r
    values.
    
    Requires ICobj.sigma to be defined already
    
    * Arguments *
    
    ICobj - The initial conditions object for which rho will be calculated
    
    * Output *
    Returns dictionary containing:
        dict['rho'] : 2D array, rho at all pairs of points (z,r)
        dict['z']   : a 1D array of z points
        dict['r']   : a 1D array of r points
        
    If output=filename, dictionary is pickled and saved to filename
    
    To be safe, keep all units in Msol and au
    """
    # Get what's need from the IC object
    settings = ICobj.settings
    
    # PARSE SETTINGS
    # Rho calculation parameters
    nr = settings.rho_calc.nr
    nz = settings.rho_calc.nz
    rmin = ICobj.sigma.r_bins.min()
    rmax = ICobj.sigma.r_bins.max()
    # Initialize r,z, and rho
    r = np.linspace(rmin,rmax,nr)
    rho = SimArray(np.zeros([nz,nr]), 'Msol au**-3')
    
    start_time = time.time()
    
    for n in range(nr):
        
        print '************************************'
        print 'Calculating rho(z) - {0} of {1}'.format(n+1,nr)
        print '{0} min elapsed'.format((time.time()-start_time)/60)
        print '************************************'
        rho_vector, z = calc_rho.rho_z(ICobj, r[[n]])
        rho[:,n] = rho_vector
        
    # Convert to the units generated by calc_rho
    rho.convert_units(rho_vector.units)
    
    return rho, z, r

class rho_from_array:
    """
    THIS IS THE RHO CLASS
    
    Upon initialization:
    Take 2D array rho(z,r) on the grid defined by the 1D arrays z and r and 
    create a 2D spline interpolation.  Points outside of z,r are taken to be
    zero.  Also calculates the inverse CDF for rho(z) at all r points.
    
    USAGE:
    
    INITIALIZE RHO:
    rho = rho_from_array(ICobj, rhoarray, z, r)
    
    USE IT!
    rho(z,r):  gives the rho spline evaluated at points z,r.  Returns an N-D
    array evaluated over the N-D arrays z, r
    
    rho.cdf_inv(m,r):   returns the cdf inverse evaluate at m for a given r.
    IE, for 0 < m < 1, returns z.
    
    rho.save(filename):     saves rho to filename
    rho.save():             saves rho to filename defined in ICobj.settings
    
    """
    
    def __init__(self, ICobj, rho, z, r):
        """
        Initialize
        """
        self._parent = ICobj
        self._rho_spline = interp.RectBivariateSpline(z,r,rho)
        self.rho_binned = rho
        self.r_bins = r
        self.z_bins = z
        
        # Generate inverse cdf spline (used by cdf_inv)
        self._cdf_inv_gen(rho, z, r)
        # Generate radial derivative of rho (used by drho_dr)
        self._radial_derivative()
        
        
    def __call__(self,z,r):
        
        return self.rho(z,r)
    
    def _cdf_inv_gen(self, rho, z, r):
        # Calculate the inverse CDF (kinda works?)
        cdf_inv = []
        # Generate the inverse CDF
        for n in range(len(r)):
            
            cdf_inv.append(calc_rho.cdfinv_z(z,rho[:,n]))
        
        self._cdf_inv = cdf_inv
        
    def _radial_derivative(self):
        """
        Generate the radial derivative of rho
        """
        z = self.z_bins
        r = self.r_bins
        rho = self.rho_binned
        
        dz = z[[1]] - z[[0]]
        dr = r[[1]] - r[[0]]
        
        drho_dr_binned = np.gradient(rho, dz, dr)[1]
        
        drho_dr_spline = interp.RectBivariateSpline(z, r, drho_dr_binned)
        self._drho_dr = drho_dr_spline
        
        

    def cdf_inv(self,m,r):
        """
        A callable interface for the inverse CDF.
        
        cdf_inv(m,r) returns z at a given r for 0 < m <1
        
        IF m and r are the same length, the CDF_inv is calculated over the
        pairs m(i), r(i).
        
        IF one argument is a single point and the other is an array, the value
        of the single point is used for every evaluation.  eg:
            r = SimArray(np.linspace(0, 20, 100), 'au')
            m = 0.5
            
            cdf_vals = cdf_inv(m, r) # Returns z at cdf = 0.5 for all r
            
        """
        
        # Make them iterable if they are floats/0D arrays
        if not hasattr(m, '__iter__'): m = np.array(m).reshape(1)
        if not hasattr(r, '__iter__'): r = np.array(r).reshape(1)
        # Check to see if one of the arrays is longer than the other.  IF so,
        # assume that one is length one
        if np.prod(m.shape) > np.prod(r.shape):
            
            r = r*np.ones(m.shape)
            
        elif np.prod(m.shape) < np.prod(r.shape):
            
            m = m*np.ones(r.shape)
        
        # Check units
        runit = self.r_bins.units
        zunit = self.z_bins.units
        r = isaac.match_units(r, runit)[0]
            
        # Initialize
        n_pts = len(r)
        z_out = SimArray(np.zeros([len(r)]), zunit)
        dr = self.r_bins[[1]] - self.r_bins[[0]]
        r_indices = np.digitize(r, self.r_bins)
        # Ignore values outside of the r range
        mask = (r >= self.r_bins.min()) & (r < self.r_bins.max())
        z_ind = np.arange(n_pts)
        
        # Now calculate the values of z_out
        for i,j in zip(z_ind[mask], r_indices[mask]):
            
            z_lo = self._cdf_inv[j-1](m[i])
            z_hi = self._cdf_inv[j](m[i])
            z_out[i] = z_lo + ((z_hi-z_lo)/dr)*(r[[i]] - self.r_bins[[j-1]])
            
        return z_out
            

    def rho(self,z,r):
        """
        A Callable method that works like a spline but handles units.
        
        returns rho(z,r), an N-D array evaluated over the N-D arrays z, r
        """
        
        # Fix up units
        zunit = self.z_bins.units
        runit = self.r_bins.units
        rho_unit = self.rho_binned.units
        
        z = isaac.match_units(z, zunit)[0]
        r = isaac.match_units(r, runit)[0]
        
        if not hasattr(z, '__iter__'):
            
            rho_out = SimArray(self._rho_spline(z,r), rho_unit)
            
        else:
            
            rho_out = np.zeros(z.shape)
            iterator = np.nditer([z,r], flags=['multi_index'])
            
            while not iterator.finished:
                
                z_val, r_val = iterator.value
                ind = iterator.multi_index
                rho_out[ind] = self._rho_spline(z_val, r_val)
                iterator.iternext()
                
            rho_out = SimArray(rho_out, rho_unit)                
                        
        return rho_out
        
    def drho_dr(self, z, r):
        """
        Radial derivative of rho.  A callable method that works like a spline
        but handles units.
        
        USAGE:
        
        drho_dr(z,r) returns the radial derivative of rho at z, r
        """
        
        # Set-up units
        zunit = self.z_bins.units
        runit = self.r_bins.units
        rho_unit = self.rho_binned.units
        drho_unit = rho_unit/runit
        
        # Put z, r in the correct units
        z = isaac.match_units(z, zunit)[0]
        r = isaac.match_units(r, runit)[0]
        
        # Iterate over drho        
        if not hasattr(z, '__iter__'):
            
            drho = self._drho_dr(z,r)
            
        else:
            
            drho = np.zeros(z.shape)
            iterator = np.nditer([z,r], flags=['multi_index'])
            
            while not iterator.finished:
                
                z_val, r_val = iterator.value
                ind = iterator.multi_index
                drho[ind] = self._drho_dr(z_val, r_val)
                iterator.iternext()
                        
        # Fix up units
        drho = isaac.match_units(drho, drho_unit)[0]
        
        return drho

    def copy(self):
        """
        Returns a copy of the rho object
        """
        return copier.copy(self)
        
    def save(self, filename = None):
        """
        Saves rho to filename.  If filename = None, tries to save to the 
        filename contained in the ICobj that created rho:
            
            self._parent.settings.filenames.rhoFileName
        """
        if filename is None:
            
            filename = self._parent.settings.filenames.rhoFileName
         
        # Generate a dictionary containing rho_binned, z_bins, r_bins
        save_dict = {\
        'rho': self.rho_binned,\
        'z': self.z_bins,\
        'r': self.r_bins}
        
        pickle.dump(save_dict,open(filename,'wb'))
        print 'rho(z,r) saved to {}'.format(filename)
        
        # Update parent filename
        self._parent.settings.filenames.rhoFileName = filename