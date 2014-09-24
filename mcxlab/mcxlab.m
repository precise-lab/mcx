function [flux,detphoton]=mcxlab(cfg)
%
%====================================================================
%      MCXLAB - Monte Carlo eXtreme (MCX) for MATLAB/GNU Octave
%--------------------------------------------------------------------
%Copyright (c) 2010-2014 Qianqian Fang <fangq at nmr.mgh.harvard.edu>
%                      URL: http://mcx.sf.net
%====================================================================
%
% Format:
%    [flux,detphoton]=mcxlab(cfg);
%
% Input:
%    cfg: a struct, or struct array. Each element of cfg defines 
%         the parameters associated with a simulation. 
%
%    It may contain the following fields:
%
%     *cfg.nphoton:    the total number of photons to be simulated (integer)
%     *cfg.vol:        a 3D array specifying the media index in the domain
%     *cfg.prop:       an N by 4 array, each row specifies [mua, mus, g, n] in order.
%                      the first row corresponds to medium type 0 which is 
%                      typically [0 0 1 1]. The second row is type 1, and so on.
%     *cfg.tstart:     starting time of the simulation (in seconds)
%     *cfg.tstep:      time-gate width of the simulation (in seconds)
%     *cfg.tend:       ending time of the simulation (in second)
%     *cfg.srcpos:     a 1 by 3 vector, the position of the source in grid unit
%     *cfg.srcdir:     a 1 by 3 vector, specifying the incident vector
%      cfg.sradius:    radius within which we use atomic operations (in grid) [0.0]
%                      sradius=0 to disable atomic operations; if sradius=-1,
%                      use cfg.crop0 and crop1 to define a cubic atomic zone; if
%                      sradius=-2, perform atomic operations in the entire domain 
%      cfg.nblocksize: how many CUDA thread blocks to be used [64]
%      cfg.nthread:    the total CUDA thread number [2048]
%      cfg.maxgate:    the num of time-gates per simulation
%      cfg.session:    a string for output file names (used when no return variables)
%      cfg.seed:       seed for the random number generator (integer) [0]
%      cfg.maxdetphoton:   maximum number of photons saved by the detectors [1000000]
%      cfg.detpos:     an N by 4 array, each row specifying a detector: [x,y,z,radius]
%      cfg.respin:     repeat simulation for the given time (integer) [1]
%      cfg.gpuid:      which GPU to use (run 'mcx -L' to list all GPUs) [1]
%      cfg.isreflect:  [1]-consider refractive index mismatch, 0-matched index
%      cfg.isrefint:   1-ref. index mismatch at inner boundaries, [0]-matched index
%      cfg.isnormalized:[1]-normalize the output flux to unitary source, 0-no reflection
%      cfg.issavedet:  1-to save detected photon partial path length, [0]-do not save
%      cfg.issave2pt:  [1]-to save flux distribution, 0-do not save
%      cfg.issrcfrom0: 1-first voxel is [0 0 0], [0]- first voxel is [1 1 1]
%      cfg.isgpuinfo:  1-print GPU info, [0]-do not print
%      cfg.autopilot:  1-automatically set threads and blocks, [0]-use nthread/nblocksize
%      cfg.minenergy:  terminate photon when weight less than this level (float) [0.0]
%      cfg.unitinmm:   defines the length unit for a grid edge length [1.0]
%      cfg.shapes:     a JSON string for additional shapes in the grid
%      cfg.reseedlimit:number of scattering events before reseeding RNG
%      cfg.srctype:    source type, the parameters of the src are specified by cfg.srcparam{1,2}
%                      'pencil' - default, pencil beam, no param needed
%                      'isotropic' - isotropic source, no param needed
%                      'cone' - uniform cone beam, srcparam1(1) is the half-angle in radian
%                      'gaussian' - a collimated gaussian beam, srcparam1(1) specifies the waist radius (in voxels)
%                      'planar' - a 3D quadrilateral uniform planar source, with three corners specified 
%                                by srcpos, srcpos+srcparam1(1:3) and srcpos+srcparam2(1:3)
%                      'pattern' - a 3D quadrilateral pattern illumination, same as above, except
%                                srcparam1(4) and srcparam2(4) specify the pattern array x/y dimensions,
%                                and srcpattern is a pattern array, valued between [0-1]. 
%                      'fourier' - spatial frequency domain source, similar to 'planar', except
%                                the integer parts of srcparam1(4) and srcparam2(4) represent
%                                the x/y frequencies; the fraction part of srcparam1(4) multiplies
%                                2*pi represents the phase shift (phi0); 1.0 minus the fraction part of
%                                srcparam2(4) is the modulation depth (M). Put in equations:
%                                    S=0.5*[1+M*cos(2*pi*(fx*x+fy*y)+phi0)], (0<=x,y,M<=1)
%                      'arcsine' - similar to isotropic, except the zenith angle is uniform
%                                distribution, rather than a sine distribution.
%                      'disk' - a uniform disk source pointing along srcdir; the radius is 
%                               set by srcparam1(1) (in grid unit)
%                      'fourierx' - a general Fourier source, the parameters are 
%                               srcparam1: [v1x,v1y,v1z,|v2|], srcparam2: [kx,ky,phi0,M]
%                               normalized vectors satisfy: srcdir cross v1=v2
%                               the phase shift is phi0*2*pi
%                      'fourierx2d' - a general 2D Fourier basis, parameters
%                               srcparam1: [v1x,v1y,v1z,|v2|], srcparam2: [kx,ky,phix,phiy]
%                               the phase shift is phi{x,y}*2*pi
%                      'zgaussian' - an angular gaussian beam, srcparam1(0) specifies the variance in the zenith angle
%      cfg.{srcparam1,srcparam2}: 1x4 vectors, see cfg.srctype for details
%      cfg.srcpattern: see cfg.srctype for details
%      cfg.voidtime:   for wide-field sources, [1]-start timer at launch, 0-when entering 
%                      the first non-zero voxel
%
%      fields with * are required; options in [] are the default values
%
% Output:
%      flux: a struct array, with a length equals to that of cfg.
%            For each element of flux, flux(i).data is a 4D array with
%            dimensions specified by [size(vol) total-time-gates]. 
%            The content of the array is the normalized flux at 
%            each voxel of each time-gate.
%      detphoton: a struct array, with a length equals to that of cfg.
%            For each element of detphoton, detphoton(i).data is a 2D array with
%            dimensions [size(cfg.prop,1)+1 saved-photon-num]. The first row
%            is the ID(>0) of the detector that captures the photon; the second row
%	     saves the number of scattering events of each exiting photon; the rest rows
%	     are the partial path lengths (in grid unit) traveling in medium 1 up 
%            to the last. If you set cfg.unitinmm, you need to multiply the path-lengths
%            to convert them to mm unit.
%      vol: (optional) a struct array, each element is a preprocessed volume
%            corresponding to each instance of cfg. Each volume is a 3D uint8 array.
%
%      if detphoton is ignored, the detected photon will be saved in a .mch file 
%      if cfg.issavedeet=1; if no output is given, the flux will be saved to a 
%      .mc2 file if cfg.issave2pt=1 (which is true by default).
%
% Example:
%      cfg.nphoton=1e7;
%      cfg.vol=uint8(ones(60,60,60));
%      cfg.srcpos=[30 30 1];
%      cfg.srcdir=[0 0 1];
%      cfg.gpuid=1;
%      cfg.autopilot=1;
%      cfg.prop=[0 0 1 1;0.005 1 0 1.37];
%      cfg.tstart=0;
%      cfg.tend=5e-9;
%      cfg.tstep=5e-10;
%      % calculate the flux distribution with the given config
%      flux=mcxlab(cfg);
%
%      cfgs(1)=cfg;
%      cfgs(2)=cfg;
%      cfgs(1).isreflect=0;
%      cfgs(2).isreflect=1;
%      cfgs(2).issavedet=1;
%      cfgs(2).detpos=[30 20 1 1;30 40 1 1;20 30 1 1;40 30 1 1];
%      % calculate the flux and partial path lengths for the two configurations
%      [fluxs,detps]=mcxlab(cfgs);
%
%      imagesc(squeeze(log(fluxs(1).data(:,30,:,1)))-squeeze(log(fluxs(2).data(:,30,:,1))));
%
%
% This function is part of Monte Carlo eXtreme (MCX) URL: http://mcx.sf.net
%
% License: GNU General Public License version 3, please read LICENSE.txt for details
%
