"""
pyart.io.cfradial
=================

Utilities for reading CF/Radial files.

.. autosummary::
    :toctree: generated/

    read_cfradial
    write_cfradial
    _find_all_meta_group_vars
    _ncvar_to_dict
    _stream_ncvar_to_dict
    _stream_to_2d
    _create_ncvar

"""

import getpass
import datetime
import platform

import numpy as np
import netCDF4

from ..config import FileMetadata
from .common import stringarray_to_chararray
from ..core.radar import Radar


# Variables and dimensions in the instrument_parameter convention and
# radar_parameters sub-convention that will be read from and written to
# CfRadial files using Py-ART.
# The meta_group attribute cannot be used to identify these parameters as
# it is often set incorrectly.
_INSTRUMENT_PARAMS_DIMS = {
    # instrument_parameters sub-convention
    'frequency': ('frequency'),
    'follow_mode': ('sweep', 'string_length'),
    'pulse_width': ('time', ),
    'prt_mode': ('sweep', 'string_length'),
    'prt': ('time', ),
    'prt_ratio': ('time', ),
    'polarization_mode': ('sweep', 'string_length'),
    'nyquist_velocity': ('time', ),
    'unambiguous_range': ('time', ),
    'n_samples': ('time', ),
    'sampling_ratio': ('time', ),
    # radar_parameters sub-convention
    'radar_antenna_gain_h': (),
    'radar_antenna_gain_v': (),
    'radar_beam_width_h': (),
    'radar_beam_width_v': (),
    'radar_reciever_bandwidth': (),
    'radar_measured_transmit_power_h': ('time', ),
    'radar_measured_transmit_power_v': ('time', ),
    'radar_rx_bandwidth': (),           # non-standard
    'measured_transmit_power_v': ('time', ),    # non-standard
    'measured_transmit_power_h': ('time', ),    # non-standard
}


def read_cfradial(filename, field_names=None, additional_metadata=None,
                  file_field_names=False, exclude_fields=None):
    """
    Read a Cfradial netCDF file.

    Parameters
    ----------
    filename : str
        Name of CF/Radial netCDF file to read data from.
    field_names : dict, optional
        Dictionary mapping field names in the file names to radar field names.
        Unlike other read functions, fields not in this dictionary or having a
        value of None are still included in the radar.fields dictionary, to
        exclude them use the `exclude_fields` parameter. Fields which are
        mapped by this dictionary will be renamed from key to value.
    additional_metadata : dict of dicts, optional
        This parameter is not used, it is included for uniformity.
    file_field_names : bool, optional
        True to force the use of the field names from the file in which
        case the `field_names` parameter is ignored. False will use to
        `field_names` parameter to rename fields.
    exclude_fields : list or None, optional
        List of fields to exclude from the radar object. This is applied
        after the `file_field_names` and `field_names` parameters.

    Returns
    -------
    radar : Radar
        Radar object.

    Notes
    -----
    This function has not been tested on "stream" Cfradial files.

    """
    # create metadata retrieval object
    filemetadata = FileMetadata('cfradial', field_names, additional_metadata,
                                file_field_names, exclude_fields)

    # read the data
    ncobj = netCDF4.Dataset(filename)
    ncvars = ncobj.variables

    # 4.1 Global attribute -> move to metadata dictionary
    metadata = dict([(k, getattr(ncobj, k)) for k in ncobj.ncattrs()])

    # 4.2 Dimensions (do nothing) TODO check if n_points present

    # 4.3 Global variable -> move to metadata dictionary
    if 'volume_number' in ncvars:
        metadata['volume_number'] = int(ncvars['volume_number'][:])
    else:
        metadata['volume_number'] = 0

    global_vars = {'platform_type': 'fixed', 'instrument_type': 'radar',
                   'primary_axis': 'axis_z'}
    # ignore time_* global variables, these are calculated from the time
    # variable when the file is written.
    for var, default_value in global_vars.iteritems():
        if var in ncvars:
            metadata[var] = str(netCDF4.chartostring(ncvars[var][:]))
        else:
            metadata[var] = default_value

    # 4.4 coordinate variables -> create attribute dictionaries
    time = _ncvar_to_dict(ncvars['time'])
    _range = _ncvar_to_dict(ncvars['range'])

    # 4.5 Ray dimension variables TODO working with this

    # 4.6 Location variables -> create attribute dictionaries
    latitude = _ncvar_to_dict(ncvars['latitude'])
    longitude = _ncvar_to_dict(ncvars['longitude'])
    altitude = _ncvar_to_dict(ncvars['altitude'])
    if 'altitude_agl' in ncvars:
        altitude_agl = _ncvar_to_dict(ncvars['altitude_agl'])
    else:
        altitude_agl = None

    # 4.7 Sweep variables -> create atrribute dictionaries
    sweep_number = _ncvar_to_dict(ncvars['sweep_number'])
    sweep_mode = _ncvar_to_dict(ncvars['sweep_mode'])
    fixed_angle = _ncvar_to_dict(ncvars['fixed_angle'])
    sweep_start_ray_index = _ncvar_to_dict(ncvars['sweep_start_ray_index'])
    sweep_end_ray_index = _ncvar_to_dict(ncvars['sweep_end_ray_index'])
    if 'target_scan_rate' in ncvars:
        target_scan_rate = _ncvar_to_dict(ncvars['target_scan_rate'])
    else:
        target_scan_rate = None

    # first sweep mode determines scan_type
    mode = str(netCDF4.chartostring(sweep_mode['data'][0]))

    # options specified in the CF/Radial standard
    if mode == 'rhi':
        scan_type = 'rhi'
    elif mode == 'vertical_pointing':
        scan_type = 'vpt'
    elif mode == 'azimuth_surveillance':
        scan_type = 'ppi'
    elif mode == 'elevation_surveillance':
        scan_type = 'rhi'
    elif mode == 'manual_ppi':
        scan_type = 'ppi'
    elif mode == 'manual_rhi':
        scan_type = 'rhi'

    # fallback types
    elif 'sur' in mode:
        scan_type = 'ppi'
    elif 'sec' in mode:
        scan_type = 'sector'
    elif 'rhi' in mode:
        scan_type = 'rhi'
    else:
        scan_type = 'other'

    # 4.8 Sensor pointing variables -> create attribute dictionaries
    azimuth = _ncvar_to_dict(ncvars['azimuth'])
    elevation = _ncvar_to_dict(ncvars['elevation'])
    if 'scan_rate' in ncvars:
        scan_rate = _ncvar_to_dict(ncvars['scan_rate'])
    else:
        scan_rate = None

    if 'antenna_transition' in ncvars:
        antenna_transition = _ncvar_to_dict(ncvars['antenna_transition'])
    else:
        antenna_transition = None

    # 4.9 Moving platform geo-reference variables
    # Aircraft specific varaibles
    if 'rotation' in ncvars:
        rotation = _ncvar_to_dict(ncvars['rotation'])
    else:
        rotation = None

    if 'tilt' in ncvars:
        tilt = _ncvar_to_dict(ncvars['tilt'])
    else:
        tilt = None

    if 'roll' in ncvars:
        roll = _ncvar_to_dict(ncvars['roll'])
    else:
        roll = None

    if 'drift' in ncvars:
        drift = _ncvar_to_dict(ncvars['drift'])
    else:
        drift = None

    if 'heading' in ncvars:
        heading = _ncvar_to_dict(ncvars['heading'])
    else:
        heading = None

    if 'pitch' in ncvars:
        pitch = _ncvar_to_dict(ncvars['pitch'])
    else:
        pitch = None

    if 'georefs_applied' in ncvars:
        georefs_applied = _ncvar_to_dict(ncvars['georefs_applied'])
    else:
        georefs_applied = None

    # 4.10 Moments field data variables -> field attribute dictionary
    if 'ray_start_index' not in ncvars:     # Cfradial

        fields = {}
        # all variables with dimensions of 'time', 'range' are fields
        keys = [k for k, v in ncvars.iteritems()
                if v.dimensions == ('time', 'range')]
        for key in keys:
            field_name = filemetadata.get_field_name(key)
            if field_name is None:
                if exclude_fields is not None and key in exclude_fields:
                    continue
                field_name = key
            fields[field_name] = _ncvar_to_dict(ncvars[key])

    else:  # stream file
        ngates = ncvars['ray_start_index'][-1] + ncvars['ray_n_gates'][-1]
        sweeps = ncvars['sweep_start_ray_index'][:]
        sweepe = ncvars['sweep_end_ray_index'][:]
        ray_len = ncvars['ray_n_gates'][:]
        maxgates = ncvars['range'].shape[0]
        nrays = ncvars['time'].shape[0]
        ray_start_index = ncvars['ray_start_index'][:]
        keys = [k for k, v in ncvars.iteritems() if v.shape == (ngates,)]

        fields = {}
        for key in keys:
            field_name = filemetadata.get_field_name(key)
            if field_name is None:
                if exclude_fields is not None and key in exclude_fields:
                    continue
                field_name = key
            fields[field_name] = _stream_ncvar_to_dict(
                ncvars[key], sweeps, sweepe, ray_len, maxgates, nrays,
                ray_start_index)

    # 4.5 instrument_parameters sub-convention -> instrument_parameters dict
    # 4.6 radar_parameters sub-convention -> instrument_parameters dict
    keys = [k for k in _INSTRUMENT_PARAMS_DIMS.keys() if k in ncvars]
    instrument_parameters = dict((k, _ncvar_to_dict(ncvars[k])) for k in keys)
    if instrument_parameters == {}:  # if no parameters set to None
        instrument_parameters = None

    # 4.7 lidar_parameters sub-convention -> skip

    # 4.8 radar_calibration sub-convention -> radar_calibration
    keys = _find_all_meta_group_vars(ncvars, 'radar_calibration')
    radar_calibration = dict((k, _ncvar_to_dict(ncvars[k])) for k in keys)

    return Radar(
        time, _range, fields, metadata, scan_type,
        latitude, longitude, altitude,
        sweep_number, sweep_mode, fixed_angle, sweep_start_ray_index,
        sweep_end_ray_index,
        azimuth, elevation,
        instrument_parameters=instrument_parameters,
        radar_calibration=radar_calibration,
        altitude_agl=altitude_agl,
        scan_rate=scan_rate,
        antenna_transition=antenna_transition,
        target_scan_rate=target_scan_rate,
        rotation=rotation, tilt=tilt, roll=roll, drift=drift, heading=heading,
        pitch=pitch, georefs_applied=georefs_applied)


def _find_all_meta_group_vars(ncvars, meta_group_name):
    """
    Return a list of all variables which are in a given meta_group.
    """
    return [k for k, v in ncvars.iteritems() if 'meta_group' in v.ncattrs()
            and v.meta_group == meta_group_name]


def _ncvar_to_dict(ncvar):
    """ Convert a NetCDF Dataset variable to a dictionary. """
    d = dict((k, getattr(ncvar, k)) for k in ncvar.ncattrs())
    d['data'] = ncvar[:]
    if np.isscalar(d['data']):
        # netCDF4 1.1.0+ returns a scalar for 0-dim array, we always want
        # 1-dim+ arrays with a valid shape.
        d['data'] = np.array(d['data'])
        d['data'].shape = (1, )
    return d


def _stream_ncvar_to_dict(ncvar, sweeps, sweepe, ray_len, maxgates, nrays,
                          ray_start_index):
    """ Convert a Stream NetCDF Dataset variable to a dict. """
    d = dict((k, getattr(ncvar, k)) for k in ncvar.ncattrs())
    data = _stream_to_2d(ncvar[:], sweeps, sweepe, ray_len, maxgates, nrays,
                         ray_start_index)
    d['data'] = data
    return d


def _stream_to_2d(data, sweeps, sweepe, ray_len, maxgates, nrays,
                  ray_start_index):
    """ Convert a 1D stream to a 2D array. """
    # XXX clean this up, need to find sample data
    time_range = np.ma.zeros([nrays, maxgates]) - 9999.0
    cp = 0
    for sweep_number in range(len(sweepe)):
        ss = sweeps[sweep_number]
        se = sweepe[sweep_number]
        rle = ray_len[sweeps[sweep_number]]

        if ray_len[ss:se].sum() == rle * (se - ss):
            time_range[ss:se, 0:rle] = (
                data[cp:cp + (se - ss) * rle].reshape(se - ss, rle))
            cp += (se - ss) * rle
        else:
            for rn in range(se - ss):
                time_range[ss + rn, 0:ray_len[ss + rn]] = (
                    data[ray_start_index[ss + rn]:ray_start_index[ss + rn] +
                         ray_len[ss+rn]])
            cp += ray_len[ss:se].sum()
    return time_range


def write_cfradial(filename, radar, format='NETCDF4', time_reference=None,
                   arm_time_variables=False):
    """
    Write a Radar object to a CF/Radial compliant netCDF file.

    The files produced by this routine follow the `CF/Radial standard`_.
    Attempts are also made to to meet many of the standards outlined in the
    `ARM Data File Standards`_.

    .. _CF/Radial standard: http://www.ral.ucar.edu/projects/titan/docs/radial_formats/cfradial.html
    .. _ARM Data File Standards: https://docs.google.com/document/d/1gBMw4Kje6v8LBlsrjaGFfSLoU0jRx-07TIazpthZGt0/edit?pli=1

    Parameters
    ----------
    filename : str
        Filename to create.
    radar : Radar
        Radar object.
    format : str, optional
        NetCDF format, one of 'NETCDF4', 'NETCDF4_CLASSIC',
        'NETCDF3_CLASSIC' or 'NETCDF3_64BIT'. See netCDF4 documentation for
        details.
    time_reference : bool
        True to include a time_reference variable, False will not include
        this variable. The default, None, will include the time_reference
        variable when the first time value is non-zero.
    arm_time_variables : bool
        True to create the ARM standard time variables base_time and
        time_offset, False will not create these variables.

    """
    dataset = netCDF4.Dataset(filename, 'w', format=format)

    # determine the maximum string length
    max_str_len = len(radar.sweep_mode['data'][0])
    for k in ['follow_mode', 'prt_mode', 'polarization_mode']:
        if ((radar.instrument_parameters is not None) and
                (k in radar.instrument_parameters)):
            sdim_length = len(radar.instrument_parameters[k]['data'][0])
            max_str_len = max(max_str_len, sdim_length)
    str_len = max(max_str_len, 32)      # minimum string legth of 32

    # create time, range and sweep dimensions
    dataset.createDimension('time', None)
    dataset.createDimension('range', radar.ngates)
    dataset.createDimension('sweep', radar.nsweeps)
    dataset.createDimension('string_length', str_len)

    # global attributes
    # remove global variables from copy of metadata
    metadata_copy = dict(radar.metadata)
    global_variables = ['volume_number', 'platform_type', 'instrument_type',
                        'primary_axis', 'time_coverage_start',
                        'time_coverage_end', 'time_reference']
    for var in global_variables:
        if var in metadata_copy:
            metadata_copy.pop(var)

    # determine the history attribute if it doesn't exist, save for
    # the last attribute.
    if 'history' in metadata_copy:
        history = metadata_copy.pop('history')
    else:
        user = getpass.getuser()
        node = platform.node()
        time_str = datetime.datetime.now().isoformat()
        t = (user, node, time_str)
        history = 'created by %s on %s at %s using Py-ART' % (t)

    dataset.setncatts(metadata_copy)

    if 'Conventions' not in dataset.ncattrs():
        dataset.setncattr('Conventions', "CF/Radial")

    if 'field_names' not in dataset.ncattrs():
        dataset.setncattr('field_names', ', '.join(radar.fields.keys()))

    # history should be the last attribute, ARM standard
    dataset.setncattr('history',  history)

    # arm time variables base_time and time_offset if requested
    if arm_time_variables:
        dt = netCDF4.num2date(radar.time['data'][0], radar.time['units'])
        td = dt - datetime.datetime.utcfromtimestamp(0)
        base_time = {
            'data': np.array([td.seconds + td.days * 24 * 3600], 'int32'),
            'string': dt.strftime('%d-%b-%Y,%H:%M:%S GMT'),
            'units': 'seconds since 1970-1-1 0:00:00 0:00',
            'ancillary_variables': 'time_offset',
            'long_name': 'Base time in Epoch',
        }
        _create_ncvar(base_time, dataset, 'base_time', ())

        time_offset = {
            'data': radar.time['data'],
            'long_name': 'Time offset from base_time',
            'units': radar.time['units'].replace('T', ' ').replace('Z', ''),
            'ancillary_variables': 'time_offset',
            'calendar': 'gregorian',
        }
        _create_ncvar(time_offset, dataset, 'time_offset', ('time', ))

    # standard variables
    _create_ncvar(radar.time, dataset, 'time', ('time', ))
    _create_ncvar(radar.range, dataset, 'range', ('range', ))
    _create_ncvar(radar.azimuth, dataset, 'azimuth', ('time', ))
    _create_ncvar(radar.elevation, dataset, 'elevation', ('time', ))

    # optional sensor pointing variables
    if radar.scan_rate is not None:
        _create_ncvar(radar.scan_rate, dataset, 'scan_rate', ('time', ))
    if radar.antenna_transition is not None:
        _create_ncvar(radar.antenna_transition, dataset,
                      'antenna_transition', ('time', ))

    # fields
    for field, dic in radar.fields.iteritems():
        _create_ncvar(dic, dataset, field, ('time', 'range'))

    # sweep parameters
    _create_ncvar(radar.sweep_number, dataset, 'sweep_number', ('sweep', ))
    _create_ncvar(radar.fixed_angle, dataset, 'fixed_angle', ('sweep', ))
    _create_ncvar(radar.sweep_start_ray_index, dataset,
                  'sweep_start_ray_index', ('sweep', ))
    _create_ncvar(radar.sweep_end_ray_index, dataset,
                  'sweep_end_ray_index', ('sweep', ))
    _create_ncvar(radar.sweep_mode, dataset, 'sweep_mode',
                  ('sweep', 'string_length'))
    if radar.target_scan_rate is not None:
        _create_ncvar(radar.target_scan_rate, dataset, 'target_scan_rate',
                      ('sweep', ))

    # instrument_parameters
    if ((radar.instrument_parameters is not None) and
            ('frequency' in radar.instrument_parameters.keys())):
        size = len(radar.instrument_parameters['frequency']['data'])
        dataset.createDimension('frequency', size)

    if radar.instrument_parameters is not None:
        for k in radar.instrument_parameters.keys():
            if k in _INSTRUMENT_PARAMS_DIMS:
                dim = _INSTRUMENT_PARAMS_DIMS[k]
            else:
                dim = ()
            _create_ncvar(radar.instrument_parameters[k], dataset, k, dim)

    # radar_calibration variables
    if radar.radar_calibration is not None:
        size = [len(d['data']) for k, d in radar.radar_calibration.items()
                if k not in ['r_calib_index', 'r_calib_time']][0]
        dataset.createDimension('r_calib', size)
        for key, dic in radar.radar_calibration.items():
            if key == 'r_calib_index':
                dims = ('time', )
            elif key == 'r_calib_time':
                dims = ('r_calib', 'string_length')
            else:
                dims = ('r_calib', )
            _create_ncvar(dic, dataset, key, dims)

    # latitude, longitude, altitude, altitude_agl
    if radar.latitude['data'].size == 1:
        # stationary platform
        _create_ncvar(radar.latitude, dataset, 'latitude', ())
        _create_ncvar(radar.longitude, dataset, 'longitude', ())
        _create_ncvar(radar.altitude, dataset, 'altitude', ())
        if radar.altitude_agl is not None:
            _create_ncvar(radar.altitude_agl, dataset, 'altitude_agl', ())
    else:
        # moving platform
        _create_ncvar(radar.latitude, dataset, 'latitude', ('time', ))
        _create_ncvar(radar.longitude, dataset, 'longitude', ('time', ))
        _create_ncvar(radar.altitude, dataset, 'altitude', ('time', ))
        if radar.altitude_agl is not None:
            _create_ncvar(radar.altitude_agl, dataset, 'altitude_agl',
                          ('time', ))

    # time_coverage_start and time_coverage_end variables
    time_dim = ('string_length', )
    units = radar.time['units']
    start_dt = netCDF4.num2date(radar.time['data'][0], units)
    end_dt = netCDF4.num2date(radar.time['data'][-1], units)
    start_dic = {'data': np.array(start_dt.isoformat() + 'Z'),
                 'long_name': 'UTC time of first ray in the file',
                 'units': 'unitless'}
    end_dic = {'data': np.array(end_dt.isoformat() + 'Z'),
               'long_name': 'UTC time of last ray in the file',
               'units': 'unitless'}
    _create_ncvar(start_dic, dataset, 'time_coverage_start', time_dim)
    _create_ncvar(end_dic, dataset, 'time_coverage_end', time_dim)

    # time_reference is required or requested.
    if time_reference is None:
        if radar.time['data'][0] == 0:
            time_reference = False
        else:
            time_reference = True
    if time_reference:
        ref_dic = {'data': np.array(radar.time['units'][-20:], dtype='S'),
                   'long_name': 'UTC time reference',
                   'units': 'unitless'}
        _create_ncvar(ref_dic, dataset, 'time_reference', time_dim)

    # global variables
    # volume_number, required
    vol_dic = {'long_name': 'Volume number', 'units': 'unitless'}
    if 'volume_number' in radar.metadata:
        vol_dic['data'] = np.array([radar.metadata['volume_number']],
                                   dtype='int32')
    else:
        vol_dic['data'] = np.array([0], dtype='int32')
    _create_ncvar(vol_dic, dataset, 'volume_number', ())

    # platform_type, optional
    if 'platform_type' in radar.metadata:
        dic = {'long_name': 'Platform type',
               'data': np.array(radar.metadata['platform_type'])}
        _create_ncvar(dic, dataset, 'platform_type', ('string_length', ))

    # instrument_type, optional
    if 'instrument_type' in radar.metadata:
        dic = {'long_name': 'Instrument type',
               'data': np.array(radar.metadata['instrument_type'])}
        _create_ncvar(dic, dataset, 'instrument_type', ('string_length', ))

    # primary_axis, optional
    if 'primary_axis' in radar.metadata:
        dic = {'long_name': 'Primary axis',
               'data': np.array(radar.metadata['primary_axis'])}
        _create_ncvar(dic, dataset, 'primary_axis', ('string_length', ))

    # moving platform geo-reference variables
    if radar.rotation is not None:
        _create_ncvar(radar.rotation, dataset, 'rotation', ('time', ))

    if radar.tilt is not None:
        _create_ncvar(radar.tilt, dataset, 'tilt', ('time', ))

    if radar.roll is not None:
        _create_ncvar(radar.roll, dataset, 'roll', ('time', ))

    if radar.drift is not None:
        _create_ncvar(radar.drift, dataset, 'drift', ('time', ))

    if radar.heading is not None:
        _create_ncvar(radar.heading, dataset, 'heading', ('time', ))

    if radar.pitch is not None:
        _create_ncvar(radar.pitch, dataset, 'pitch', ('time', ))

    if radar.georefs_applied is not None:
        _create_ncvar(radar.georefs_applied, dataset, 'georefs_applied',
                      ('time', ))

    dataset.close()


def _create_ncvar(dic, dataset, name, dimensions):
    """
    Create and fill a Variable in a netCDF Dataset object.

    Parameters
    ----------
    dic : dict
        Radar dictionary to containing variable data and meta-data
    dataset : Dataset
        NetCDF dataset to create variable in.
    name : str
        Name of variable to create.
    dimension : tuple of str
        Dimension of variable.

    """
    # create array from list, etc.
    data = dic['data']
    if isinstance(data, np.ndarray) is not True:
        print "Warning, converting non-array to array:", name
        data = np.array(data)

    # convert string array to character arrays
    if data.dtype.char is 'S' and data.dtype != 'S1':
        data = stringarray_to_chararray(data)
    if data.dtype.char is 'U' and data.dtype != 'U1':
        data = stringarray_to_chararray(data)

    # create the dataset variable
    if 'least_significant_digit' in dic:
        lsd = dic['least_significant_digit']
    else:
        lsd = None
    if "_FillValue" in dic:
        fill_value = dic['_FillValue']
    else:
        fill_value = None

    ncvar = dataset.createVariable(name, data.dtype, dimensions,
                                   zlib=True, least_significant_digit=lsd,
                                   fill_value=fill_value)

    # long_name attribute first if present, ARM standard
    if 'long_name' in dic.keys():
        ncvar.setncattr('long_name', dic['long_name'])

    # units attribute second if present, ARM standard
    if 'units' in dic.keys():
        ncvar.setncattr('units', dic['units'])

    # remove _FillValue and replace to make it the third attribute.
    if '_FillValue' in ncvar.ncattrs():
        fv = ncvar._FillValue
        ncvar.delncattr('_FillValue')
        ncvar.setncattr('_FillValue', fv)

    # set all attributes
    for key, value in dic.iteritems():
        if key not in ['data', '_FillValue', 'long_name', 'units']:
            ncvar.setncattr(key, value)

    # set the data
    if data.shape == ():
        data.shape = (1,)
    if data.dtype == 'S1':  # string/char arrays
        ncvar[..., :data.shape[-1]] = data[:]
    else:
        ncvar[:] = data[:]
