'''
This module provides movie tools for level 2 IRIS SJI fits file
'''

from datetime import timedelta
import warnings

import numpy as np
from astropy.io import fits
import astropy.units as u
from astropy.wcs import WCS
from sunpy.time import parse_time
from ndcube import NDCube
from ndcube.utils.cube import convert_extra_coords_dict_to_input_format
from ndcube import utils
from ndcube.ndcube_sequence import NDCubeSequence

from irispy import iris_tools

__all__ = ['IRISMapCube']

# the following value is only appropriate for byte scaled images
BAD_PIXEL_VALUE_SCALED = -200
# the following value is only appropriate for unscaled images
BAD_PIXEL_VALUE_UNSCALED = -32768


class IRISMapCube(NDCube):
    """
    IRISMapCube

    Class representing SJI Images described by a single WCS

    Parameters
    ----------
    data: `numpy.ndarray`
        The array holding the actual data in this object.

    wcs: `ndcube.wcs.wcs.WCS`
        The WCS object containing the axes' information

    unit : `astropy.unit.Unit` or `str`
        Unit for the dataset.
        Strings that can be converted to a Unit are allowed.

    meta : dict-like object
        Additional meta information about the dataset.

    uncertainty : any type, optional
        Uncertainty in the dataset. Should have an attribute uncertainty_type
        that defines what kind of uncertainty is stored, for example "std"
        for standard deviation or "var" for variance. A metaclass defining
        such an interface is NDUncertainty - but isn’t mandatory. If the
        uncertainty has no such attribute the uncertainty is stored as
        UnknownUncertainty.
        Defaults to None.

    mask : any type, optional
        Mask for the dataset. Masks should follow the numpy convention
        that valid data points are marked by False and invalid ones with True.
        Defaults to None.

    extra_coords : iterable of `tuple`s, each with three entries
        (`str`, `int`, `astropy.units.quantity` or array-like)
        Gives the name, axis of data, and values of coordinates of a data axis
        not included in the WCS object.

    copy : `bool`, optional
        Indicates whether to save the arguments as copy. True copies every
        attribute before saving it while False tries to save every parameter
        as reference. Note however that it is not always possible to save the
        input as reference.
        Default is False.

    scaled : `bool`, optional
        Indicates if datas has been scaled.

    Examples
    --------
    >>> from irispy import sji
    >>> from irispy.data import sample
    >>> sji = read_iris_sji_level2_fits(sample.SJI_CUBE_1400)
    """

    def __init__(self, data, wcs, uncertainty=None, unit=None, meta=None,
                 mask=None, extra_coords=None, copy=False, missing_axis=None,
                 scaled=None):
        """
        Initialization of Slit Jaw Imager
        """
        warnings.warn("This class is still in early stages of development. API not stable.")
        # Set whether SJI data is scaled or not.
        self.scaled = scaled
        # Initialize IRISMapCube.
        super().__init__(data, wcs, uncertainty=uncertainty, mask=mask,
                         meta=meta, unit=unit, extra_coords=extra_coords,
                         copy=copy, missing_axis=missing_axis)

    def __repr__(self):
        #Conversion of the start date of OBS
        startobs = self.meta.get("STARTOBS", None)
        startobs = startobs.isoformat() if startobs else None
        #Conversion of the end date of OBS
        endobs = self.meta.get("ENDOBS", None)
        endobs = endobs.isoformat() if endobs else None
        #Conversion of the instance start and end of OBS
        if isinstance(self.extra_coords["TIME"]["value"], np.ndarray):
            instance_start = self.extra_coords["TIME"]["value"][0]
            instance_end = self.extra_coords["TIME"]["value"][-1]
        else:
            instance_start = self.extra_coords["TIME"]["value"]
            instance_end = self.extra_coords["TIME"]["value"]
        instance_start = instance_start.isoformat() if instance_start else None
        instance_end = instance_end.isoformat() if instance_end else None
        #Representation of IRISMapCube object
        return (
            """
    IRISMapCube
    ---------
    Observatory:\t\t {obs}
    Instrument:\t\t\t {instrument}
    Bandpass:\t\t\t {bandpass}
    Obs. Start:\t\t\t {startobs}
    Obs. End:\t\t\t {endobs}
    Instance Start:\t\t {instance_start}
    Instance End:\t\t {instance_end}
    Total Frames in Obs.:\t {frame_num}
    IRIS Obs. id:\t\t {obs_id}
    IRIS Obs. Description:\t {obs_desc}
    Cube dimensions:\t\t {dimensions}
    Axis Types:\t\t\t {axis_types}
    """.format(obs=self.meta.get('TELESCOP', None),
               instrument=self.meta.get('INSTRUME', None),
               bandpass=self.meta.get('TWAVE1', None),
               startobs=startobs,
               endobs=endobs,
               instance_start=instance_start,
               instance_end=instance_end,
               frame_num=self.meta.get("NBFRAMES", None),
               obs_id=self.meta.get('OBSID', None),
               obs_desc=self.meta.get('OBS_DESC', None),
               axis_types=self.world_axis_physical_types,
               dimensions=self.dimensions))

    def apply_exposure_time_correction(self, undo=False, force=False):
        """
        Applies or undoes exposure time correction to data and uncertainty and adjusts unit.

        Correction is only applied (undone) if the object's unit doesn't (does)
        already include inverse time.  This can be overridden so that correction
        is applied (undone) regardless of unit by setting force=True.

        Parameters
        ----------
        undo: `bool`
            If False, exposure time correction is applied.
            If True, exposure time correction is removed.
            Default=False

        copy: `bool`
            If True a new instance with the converted data values is returned.
            If False, the current instance is overwritten.
            Default=False

        force: `bool`
            If not True, applies (undoes) exposure time correction only if unit
            doesn't (does) already include inverse time.
            If True, correction is applied (undone) regardless of unit.  Unit is still
            adjusted accordingly.

        Returns
        -------
        result: `None` or `IRISMapCube`
            If copy=False, the original IRISMapCube is modified with the exposure
            time correction applied (undone).
            If copy=True, a new IRISMapCube is returned with the correction
            applied (undone).

        """
        # Raise an error if this method is called while memmap is used
        if not self.scaled:
            raise ValueError("This method is not available as you are using memmap")
        # Get exposure time in seconds and change array's shape so that
        # it can be broadcast with data and uncertainty arrays.
        exposure_time_s = u.Quantity(self.extra_coords["EXPOSURE TIME"]["value"], unit='s').value
        if not np.isscalar(self.extra_coords["EXPOSURE TIME"]["value"]):
            if self.data.ndim == 1:
                pass
            elif self.data.ndim == 2:
                exposure_time_s = exposure_time_s[:, np.newaxis]
            elif self.data.ndim == 3:
                exposure_time_s = exposure_time_s[:, np.newaxis, np.newaxis]
            else:
                raise ValueError(
                    "IRISMapCube dimensions must be 2 or 3. Dimensions={0}".format(
                        self.data.ndim))
        # Based on value on undo kwarg, apply or remove exposure time correction.
        if undo is True:
            new_data_arrays, new_unit = iris_tools.uncalculate_exposure_time_correction(
                (self.data, self.uncertainty.array), self.unit, exposure_time_s, force=force)
        else:
            new_data_arrays, new_unit = iris_tools.calculate_exposure_time_correction(
                (self.data, self.uncertainty.array), self.unit, exposure_time_s, force=force)
        # Return new instance of IRISMapCube with correction applied/undone.
        return IRISMapCube(
            data=new_data_arrays[0], wcs=self.wcs, uncertainty=new_data_arrays[1],
            unit=new_unit, meta=self.meta, mask=self.mask, missing_axis=self.missing_axis,
            extra_coords=convert_extra_coords_dict_to_input_format(self.extra_coords,
                                                                   self.missing_axis))


class IRISMapCubeSequence(NDCubeSequence):
    """Class for holding, slicing and plotting IRIS SJI data.

    This class contains all the functionality of its super class with
    some additional functionalities.

    Parameters
    ----------
    data_list: `list`
        List of `IRISMapCube` objects from the same OBS ID.
        Must also contain the 'detector type' in its meta attribute.

    meta: `dict` or header object
        Metadata associated with the sequence.

    common_axis: `int`
        The axis of the NDCubes corresponding to time.

    """
    def __init__(self, data_list, meta=None, common_axis=0):
        # Check that all SJI data are coming from the same OBS ID.
        if np.any([cube.meta["OBSID"] != data_list[0].meta["OBSID"] for cube in data_list]):
            raise ValueError("Constituent IRISMapCube objects must have same "
                             "value of 'OBSID' in its meta.")
        # Initialize Sequence.
        super().__init__(data_list, meta=meta, common_axis=common_axis)

    def __repr__(self):
        #Conversion of the start date of OBS
        startobs = self.meta.get("STARTOBS", None)
        startobs = startobs.isoformat() if startobs else None
        #Conversion of the end date of OBS
        endobs = self.meta.get("ENDOBS", None)
        endobs = endobs.isoformat() if endobs else None
        #Conversion of the instance start of OBS
        instance_start = self[0].extra_coords["TIME"]["value"]
        instance_start = instance_start.isoformat() if instance_start else None
        #Conversion of the instance end of OBS
        instance_end = self[-1].extra_coords["TIME"]["value"]
        instance_end = instance_end.isoformat() if instance_end else None
        #Representation of IRISMapCube object
        return """
IRISMapCubeSequence
---------------------
Observatory:\t\t {obs}
Instrument:\t\t {instrument}

OBS ID:\t\t\t {obs_id}
OBS Description:\t {obs_desc}
OBS period:\t\t {obs_start} -- {obs_end}

Sequence period:\t {inst_start} -- {inst_end}
Sequence Shape:\t\t {seq_shape}
Axis Types:\t\t {axis_types}

""".format(obs=self.meta.get('TELESCOP', None),
           instrument=self.meta.get('INSTRUME', None),
           obs_id=self.meta.get("OBSID", None),
           obs_desc=self.meta.get("OBS_DESC", None),
           obs_start=startobs,
           obs_end=endobs,
           inst_start=instance_start,
           inst_end=instance_end,
           seq_shape=self.dimensions,
           axis_types=self.world_axis_physical_types)

    def __getitem__(self, item):
        return self.index_as_cube[item]

    @property
    def dimensions(self):
        return self.cube_like_dimensions

    @property
    def world_axis_physical_types(self):
        return self.cube_like_world_axis_physical_types


def read_iris_sji_level2_fits(filenames, memmap=False):
    """
    Read IRIS level 2 SJI FITS from an OBS into an IRISMapCube instance

    Parameters
    ----------
    filenames: `list` of `str` or `str`
        Filename or filenames to be read.  They must all be associated with the same
        OBS number.

    memmap : `bool`
        Default value is `False`.
        If the user wants to use it, he has to set `True`

    Returns
    -------
    result: 'irispy.sji.IRISMapCube'

    """
    list_of_cubes = []
    if type(filenames) is str:
        filenames = [filenames]
    for filename in filenames:
        # Open a fits file
        hdulist = fits.open(filename, memmap=memmap, do_not_scale_image_data=memmap)
        hdulist.verify('fix')
        # Derive WCS, data and mask for NDCube from fits file.
        wcs = WCS(hdulist[0].header)
        data = hdulist[0].data
        data_nan_masked = hdulist[0].data
        if memmap:
            data_nan_masked[data == BAD_PIXEL_VALUE_UNSCALED] = 0
            mask = None
            scaled = False
            unit = iris_tools.DN_UNIT["SJI_UNSCALED"]
            uncertainty = None
        elif not memmap:
            data_nan_masked[data == BAD_PIXEL_VALUE_SCALED] = np.nan
            mask = data_nan_masked == BAD_PIXEL_VALUE_SCALED
            scaled = True
            # Derive unit and readout noise from the detector
            unit = iris_tools.DN_UNIT["SJI"]
            readout_noise = iris_tools.READOUT_NOISE["SJI"]
            # Derive uncertainty of data for NDCube from fits file.
            uncertainty = u.Quantity(np.sqrt((data_nan_masked*unit).to(u.photon).value
                                             + readout_noise.to(u.photon).value**2),
                                     unit=u.photon).to(unit).value
        # Derive exposure time from detector.
        exposure_times = hdulist[1].data[:, hdulist[1].header["EXPTIMES"]]
        # Derive extra coordinates for NDCube from fits file.
        times = np.array([parse_time(hdulist[0].header["STARTOBS"])
                          + timedelta(seconds=s)
                          for s in hdulist[1].data[:, hdulist[1].header["TIME"]]])
        pztx = hdulist[1].data[:, hdulist[1].header["PZTX"]] * u.arcsec
        pzty = hdulist[1].data[:, hdulist[1].header["PZTY"]] * u.arcsec
        xcenix = hdulist[1].data[:, hdulist[1].header["XCENIX"]] * u.arcsec
        ycenix = hdulist[1].data[:, hdulist[1].header["YCENIX"]] * u.arcsec
        obs_vrix = hdulist[1].data[:, hdulist[1].header["OBS_VRIX"]] * u.m/u.s
        ophaseix = hdulist[1].data[:, hdulist[1].header["OPHASEIX"]]
        extra_coords = [('TIME', 0, times), ("PZTX", 0, pztx), ("PZTY", 0, pzty),
                        ("XCENIX", 0, xcenix), ("YCENIX", 0, ycenix),
                        ("OBS_VRIX", 0, obs_vrix), ("OPHASEIX", 0, ophaseix),
                        ("EXPOSURE TIME", 0, exposure_times)]
        # Extraction of meta for NDCube from fits file.
        startobs = hdulist[0].header.get('STARTOBS', None)
        startobs = parse_time(startobs) if startobs else None
        endobs = hdulist[0].header.get('ENDOBS', None)
        endobs = parse_time(endobs) if endobs else None
        meta = {'TELESCOP': hdulist[0].header.get('TELESCOP', None),
                'INSTRUME': hdulist[0].header.get('INSTRUME', None),
                'TWAVE1': hdulist[0].header.get('TWAVE1', None),
                'STARTOBS': startobs,
                'ENDOBS': endobs,
                'NBFRAMES': hdulist[0].data.shape[0],
                'OBSID': hdulist[0].header.get('OBSID', None),
                'OBS_DESC': hdulist[0].header.get('OBS_DESC', None)}
        list_of_cubes.append(IRISMapCube(data_nan_masked, wcs, uncertainty=uncertainty,
                                         unit=unit, meta=meta, mask=mask,
                                         extra_coords=extra_coords, scaled=scaled))
        hdulist.close()
    if len(filenames) == 1:
        return list_of_cubes[0]
    else:
        return IRISMapCubeSequence(list_of_cubes, meta=meta, common_axis=0)
