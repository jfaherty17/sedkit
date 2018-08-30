"""
A module to generate a grid of model spectra

Author: Joe Filippazzo, jfilippazzo@stsci.edu
"""
import os
import glob
import pickle
from copy import copy
from functools import partial
from multiprocessing.dummy import Pool as ThreadPool
from multiprocessing import Pool
from pkg_resources import resource_filename

import astropy.io.ascii as ii
import astropy.table as at
import astropy.units as q
import astropy.io.votable as vo
import numpy as np
import pandas as pd
from bokeh.plotting import figure, output_file, show, save

from . import utilities as u
from .spectrum import Spectrum


# A list of all supported evolutionary models
EVO_MODELS = [os.path.basename(m).replace('.txt', '') for m in glob.glob(resource_filename('SEDkit', 'data/models/evolutionary/*'))]

def load_ModelGrid(path):
    """Load a model grid from a file
    
    Parameters
    ----------
    path: str
        The path to the saved ModelGrid
    
    Returns
    -------
    SEDkit.modelgrid.ModelGrid
        The loaded ModelGrid object
    """
    if not os.path.isfile(path):
        raise IOError("File not found:", path)
        
    data = pickle.load(open(path, 'rb'))
    
    mg = ModelGrid(data['name'], data['parameters'])
    for key, val in data.items():
        setattr(mg, key, val)
    
    return mg


class ModelGrid:
    """A class to store a model grid"""
    def __init__(self, name, parameters, wave_units=None, flux_units=None,
                 resolution=200, verbose=True, **kwargs):
        """Initialize the model grid from a directory of VO table files
        
        Parameters
        ----------
        name: str
            The name of the model grid
        wave_units: astropy.units.quantity.Quantity
            The wavelength units
        flux_units: astropy.units.quantity.Quantity
            The flux units
        resolution: float
            The resolution of the models
        verbose: bool
            Print info
        """
        # Store the path and name
        self.path = None
        self.name = name
        self.parameters = parameters
        self.wave_units = wave_units
        self.flux_units = flux_units
        self.resolution = resolution
        self.verbose = verbose
        
        # Make all args into attributes
        for key, val in kwargs.items():
            setattr(self, key, val)
            
        # Make the empty table
        columns = self.parameters+['filepath', 'spectrum']
        self.index = pd.DataFrame(columns=columns)
        
    def add_model(self, spectrum, **kwargs):
        """Add the given model with the specified parameter values as kwargs
        
        Parameters
        ----------
        spectrum: sequence
            The model spectrum
        """
        # Check that all the necessary params are included
        if not all([i in kwargs for i in self.parameters]):
            raise ValueError("Must have kwargs for", self.parameters)
            
        # Make the dictionary of new data
        kwargs.update({'spectrum': spectrum, 'filepath': None})
        new_rec = pd.DataFrame({k: [v] for k, v in kwargs.items()})

        # Add it to the index
        self.index = self.index.append(new_rec)
        
    def load(self, dirname):
        """Load a model grid from a directory of VO table XML files
        
        Parameters
        ----------
        dirname: str
            The name of the directory
        """
        # Make the path
        if not os.path.exists(dirname):
            raise IOError(dirname, ": No such directory")

        # See if there is a table of parameters
        self.path = dirname
        self.index_path = os.path.join(dirname, 'index.p')
        if not os.path.isfile(self.index_path):
            os.system("touch {}".format(self.index_path))

            # Index the models
            self.index_models(**kwargs)

        # Load the index
        self.index = pd.read_pickle(self.index_path)
        # self.index = ii.read(self.index_path)
    
        # Store the parameter ranges
        for param in self.parameters:
            setattr(self, '{}_vals'.format(param),
                    np.asarray(np.unique(self.index[param])))

    def index_models(self, parameters=None):
        """Generate model index file for faster reading
        
        Parameters
        ----------
        parameters: sequence
            The names of the parameters from the VOT files to index
        """
        # Get the files
        files = glob.glob(os.path.join(self.path, '*.xml'))
        self.n_models = len(files)
        print("Indexing {} models for {} grid...".format(self.n_models, self.name))

        # Grab the parameters and the filepath for each
        all_meta = []
        for file in files:

            try:
                # Parse the XML file
                vot = vo.parse_single_table(file)

                # Parse the SVO filter metadata
                all_params = [str(p).split() for p in vot.params]
                                    
                meta = {}
                for p in all_params:

                    # Extract the key/value pairs
                    key = p[1].split('"')[1]
                    val = p[-1].split('"')[1]
                    
                    if (parameters and key in parameters) or not parameters:

                        # Do some formatting
                        if p[2].split('"')[1] == 'float' or p[3].split('"')[1] == 'float':
                            val = float(val)

                        else:
                            val = val.replace('b&apos;','').replace('&apos','').replace('&amp;','&').strip(';')

                        # Add it to the dictionary
                        meta[key] = val

                # Add the filename
                meta['filepath'] = file
                
                # Add the data
                meta['spectrum'] = np.array([list(i) for i in vot.array]).T

                all_meta.append(meta)
                
            except IOError:
                print(file, ": Could not parse file")

        # Make the index table
        self.index = pd.DataFrame(all_meta)
        self.index.to_pickle(self.index_path)
        
        # Update attributes
        if parameters is None:
            parameters = [col for col in self.index.columns if col not in ['filepath', 'spectrum']]
        self.parameters = parameters
        
    # def get_models(self, **kwargs):
    #     """Retrieve all models with the specified parameters
    #
    #     Returns
    #     -------
    #     list
    #         A list of the spectra as SEDkit.spectrum.Spectrum objects
    #     """
    #     # Get the relevant table rows
    #     table = u.filter_table(self.index, **kwargs)
    #
    #     # Collect the spectra
    #     pool = ThreadPool(8)
    #     func = partial(FileSpectrum, wave_units=self.wave_units,
    #                    flux_units=self.flux_units)
    #     spectra = pool.map(func, table['filepath'])
    #     pool.close()
    #     pool.join()
    #
    #     # Add the metadata
    #     for n, (row, spec) in enumerate(zip(table, spectra)):
    #
    #         for col in table.colnames:
    #             setattr(spectra[n], col, row[col])
    #
    #     if len(spectra) == 1:
    #         spectra = spectra.pop()
    #
    #     return spectra
        
    def filter(self, **kwargs):
        """Retrieve all models with the specified parameters

        Returns
        -------
        list
            A list of the spectra as SEDkit.spectrum.Spectrum objects
        """
        # Get the relevant table rows
        return u.filter_table(self.index, **kwargs)
        
    def get(self, resolution=None, interp=True, **kwargs):
        """
        Retrieve the wavelength, flux, and effective radius
        for the spectrum of the given parameters

        Parameters
        ----------
        resolution: int (optional)
            The desired wavelength resolution (lambda/d_lambda)
        interp: bool
            Interpolate the model if possible

        Returns
        -------
        SEDkit.spectrum.Spectrum, list
            A Spectrum object or list of Spectrum objects
        """
        # See if the model with the desired parameters is witin the grid
        in_grid = []
        for param, value in kwargs.items():
            
            # Get the value range
            vals = getattr(self, param+'_vals')
            if min(vals) <= value <= max(vals):
                in_grid.append(True)
                
            else:
                in_grid.append(False)

        if all(in_grid):

            # See if the model with the desired parameters is a true grid point
            on_grid = []
            for param, value in kwargs.items():
            
                # Get the value range
                vals = getattr(self, param+'_vals')
                if value in vals:
                    on_grid.append(True)
                
                else:
                    on_grid.append(False)

            # Grab the data if the point is on the grid
            if all(on_grid):
                return self.get_models(**kwargs)

            # If not on the grid, interpolate to it
            else:
                # Call grid_interp method
                if interp:
                    spec_dict = self.grid_interp(**kwargs)
                else:
                    return

        else:
            param_str = ['{}={}'.format(k, v) for k, v in kwargs.items()]
            print(', '.join(param_str)+' model not in grid.')
            return
    
    def get_spectrum(self, **kwargs):
        """Retrieve the first model with the specified parameters
        
        Returns
        -------
        np.ndarray
            A numpy array of the spectrum
        """
        # Get the row index and filepath
        rows = copy(self.index)
        for arg, val in kwargs.items():
            rows = rows.loc[rows[arg] == val]
        
        if rows.empty:
            print("No models found satisfying", kwargs)
            return None
        else:
            return rows.iloc[0].spectrum
            
    def plot(self, fig=None, draw=False, **kwargs):
        """Plot the models with the given parameters
        
        Parameters
        ----------
        fig: bokeh.figure (optional)
            The figure to plot on
        draw: bool
            Draw the plot rather than just return it
        
        Returns
        -------
        bokeh.figure
            The figure
        """
        # Make the figure
        if fig is None:
            input_fig = False
            fig = figure()
            fig.xaxis.axis_label = "Wavelength [{}]".format(self.wave_units)
            fig.yaxis.axis_label = "Flux Density [{}]".format(self.flux_units)
        else:
            input_fig = True
            
        model = self.get_spectrum(**kwargs)
        if model is not None:
            
            # Plot the spectrum
            fig.line(model[0], model[1])
            
            if draw:
                show(fig)
            else:
                return fig
        else:
            return fig if input_fig else None

    def save(self, file):
        """Save the model grid to file
        
        Parameters
        ----------
        file: str
            The path for the new file
        """
        path = os.path.dirname(file)
        
        if os.path.exists(path):
            
            # Make the file if necessary
            if not os.path.isfile(file):
                os.system('touch {}'.format(file))
                
            # Write the file
            f = open(file, 'wb')
            pickle.dump(self.__dict__, f, pickle.HIGHEST_PROTOCOL)
            f.close()
            
            print("ModelGrid '{}' saved to {}".format(self.name, file))
        
    # def grid_interp(self, **kwargs):
    #     """
    #     Interpolate the grid to the desired parameters
    #
    #     Returns
    #     -------
    #     SEDkit.spectrum.Spectrum
    #         The interpolated Spectrum object
    #     """
    #     # Get the flux array
    #     flux = self.flux.copy()
    #
    #     # Get the interpolable parameters
    #     params, values = [], []
    #     target = [getattr(self, p) for p in kwargs]
    #     ranges = [getattr(self, p+'_vals') for p in kwargs]
    #     for p, v in zip(ranges, target):
    #         if len(p) > 1:
    #             params.append(p)
    #             values.append(v)
    #     values = np.asarray(values)
    #     label = '/'.join(target)
    #
    #     print(params, values)
    #     return
    #
    #     try:
    #         # Interpolate flux values at each wavelength
    #         # using a pool for multiple processes
    #         print('Interpolating grid point [{}]...'.format(label))
    #         start = time.time()
    #         pool = Pool(4)
    #         func = partial(u.interp_flux, flux=flux, params=params,
    #                        values=values)
    #         new_flux, generators = zip(*pool.map(func, mu_index))
    #         pool.close()
    #         pool.join()
    #
    #         # Clean up and time of execution
    #         new_flux = np.asarray(new_flux)
    #         generators = np.asarray(generators)
    #         print('Run time in seconds: ', time.time()-start)
    #
    #         # Interpolate mu value
    #         interp_mu = RegularGridInterpolator(params, self.mu)
    #         mu = interp_mu(np.array(values)).squeeze()
    #
    #         # Interpolate r_eff value
    #         interp_r = RegularGridInterpolator(params, self.r_eff)
    #         r_eff = interp_r(np.array(values)).squeeze()
    #
    #         # Make a dictionary to return
    #         grid_point = {'Teff': Teff, 'logg': logg, 'FeH': FeH,
    #                       'mu': mu, 'r_eff': r_eff,
    #                       'flux': new_flux, 'wave': self.wavelength,
    #                       'generators': generators}
    #
    #         return grid_point
    #
    #     except IOError:
    #         print('Grid too sparse. Could not interpolate.')
    #         return
        

class BTSettl(ModelGrid):
    """Child class for the BT-Settl model grid"""
    def __init__(self):
        """Loat the model object"""
        # List the parameters
        params = ['alpha', 'logg', 'teff', 'meta']
        
        # Inherit from base class
        super().__init__('BT-Settl', params, q.AA, q.erg/q.s/q.cm**2/q.AA)
        
        # Load the model grid
        model_path = 'data/models/atmospheric/btsettl'
        root = resource_filename('SEDkit', model_path)
        self.load(root)
        
        
class Filippazzo2016(ModelGrid):
    """Child class for the Filippazzo et al. (2016) sample"""
    def __init__(self):
        """Load the model object"""
        model_path = 'data/models/atmospheric/Filippazzo2016.p'
        root = resource_filename('SEDkit', model_path)
        
        data = pickle.load(open(root, 'rb'))
        
        # Inherit from base class
        super().__init__(data['name'], data['parameters'])
        
        # Copy to new __dict__
        for key, val in data.items():
            setattr(self, key, val)


class SpexPrismLibrary(ModelGrid):
    """Child class for the SpeX Prism Library model grid"""
    def __init__(self):
        """Loat the model object"""
        # List the parameters
        params = ['spty']
        
        # Inherit from base class
        super().__init__('SpeX Prism Library', params, q.AA,
                         q.erg/q.s/q.cm**2/q.AA)
                         
        # Load the model grid
        model_path = 'data/models/atmospheric/spexprismlibrary'
        root = resource_filename('SEDkit', model_path)
        self.load(root)
        