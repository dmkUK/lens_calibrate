#!/usr/bin/env python3

#######################################################################
#
# A script to calibrate camera lenes for lensfun
#
# Copyright (c) 2012-2016 Torsten Bronger <bronger@physik.rwth-aachen.de>
# Copyright (c) 2018-2019 Andreas Schneider <asn@cryptomilk.org>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
#######################################################################
#
# Requires: python3-exiv2
# Requires: python3-numpy
# Requires: python3-scipy
# Requires: python3-PyPDF2
#
# Requires: darktable (darktable-cli)
# Requires: hugin-tools (tca_correct)
# Requires: ImageMagick (convert)
# Requires: gnuplot
#

import os
import argparse
import configparser
import codecs
import re
import math
import multiprocessing
import numpy as np
import subprocess
import shutil
import tarfile
import tempfile
import concurrent.futures
from subprocess import DEVNULL

# ---------------------------------------------------------------------------------------------------
# lens_calibrate.py:50: DeprecationWarning: Please use `leastsq` from the `scipy.optimize` namespace,
#  the `scipy.optimize.minpack` namespace is deprecated from scipy.optimize.minpack import leastsq
# -------------------------------------------------------------------------------------------------

from scipy.optimize import leastsq

from pyexiv2.metadata import ImageMetadata

# ----------------------------------------------------------------------------------------------------------
# PyPDF2.errors.DeprecationError: PdfFileMerger is deprecated and was removed in PyPDF2 3.0.0. Use PdfMerger instead
# from PyPDF2 import PdfFileMerger
# ------------------------------------------------------------------------------------------------------------

from PyPDF2 import PdfMerger

# Sidecar for loading into hugin
# Applies a neutral basecurve and enables sharpening
DARKTABLE_DISTORTION_SIDECAR = '''<?xml version="1.0" encoding="UTF-8"?>
<x:xmpmeta xmlns:x="adobe:ns:meta/" x:xmptk="XMP Core 4.4.0-Exiv2">
 <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">
  <rdf:Description rdf:about=""
    xmlns:exif="http://ns.adobe.com/exif/1.0/"
    xmlns:xmp="http://ns.adobe.com/xap/1.0/"
    xmlns:xmpMM="http://ns.adobe.com/xap/1.0/mm/"
    xmlns:dc="http://purl.org/dc/elements/1.1/"
    xmlns:darktable="http://darktable.sf.net/"
   exif:DateTimeOriginal="2019:05:01 16:01:36"
   xmp:Rating="1"
   xmpMM:DerivedFrom="distortion.img"
   darktable:xmp_version="3"
   darktable:raw_params="0"
   darktable:auto_presets_applied="1"
   darktable:history_end="3"
   darktable:iop_order_version="2">
   <darktable:masks_history>
    <rdf:Seq/>
   </darktable:masks_history>
   <darktable:history>
    <rdf:Seq>
     <rdf:li
      darktable:num="0"
      darktable:operation="basecurve"
      darktable:enabled="1"
      darktable:modversion="6"
      darktable:params="gz09eJxjYIAAruuLrbmuK1vPmilpN2vmTLuzZ87YGRsb2zMwONgbGxcD6QYoHgVDCbAhsZkwZBFxCgB+Wg6p"
      darktable:multi_name=""
      darktable:multi_priority="0"
      darktable:iop_order="23.0000000000000"
      darktable:blendop_version="9"
      darktable:blendop_params="gz11eJxjYGBgkGAAgRNODGiAEV0AJ2iwh+CRyscOAAdeGQQ="/>
     <rdf:li
      darktable:num="1"
      darktable:operation="colorin"
      darktable:enabled="1"
      darktable:modversion="6"
      darktable:params="gz48eJzjYRgFowABWAbaAaNgwAEAPRQAEQ=="
      darktable:multi_name=""
      darktable:multi_priority="0"
      darktable:iop_order="27.0000000000000"
      darktable:blendop_version="9"
      darktable:blendop_params="gz11eJxjYGBgkGAAgRNODGiAEV0AJ2iwh+CRyscOAAdeGQQ="/>
     <rdf:li
      darktable:num="2"
      darktable:operation="colorout"
      darktable:enabled="1"
      darktable:modversion="5"
      darktable:params="gz35eJxjZBgFo4CBAQAEEAAC"
      darktable:multi_name=""
      darktable:multi_priority="0"
      darktable:iop_order="58.0000000000000"
      darktable:blendop_version="9"
      darktable:blendop_params="gz11eJxjYGBgkGAAgRNODGiAEV0AJ2iwh+CRyscOAAdeGQQ="/>
    </rdf:Seq>
   </darktable:history>
  </rdf:Description>
 </rdf:RDF>
</x:xmpmeta>
'''

# Sidecar for TCA corrections
#
# * disable basecurve
# * disable sharpen
# * disable highlight reconstruction
# * set colorin to Linear Rec2020 RGB
# * set colorin working space to Linear Rec2020 RGB
# * set colorout to Linear Rec2020 RGB
#
# Setting colorin and colorout to Linear Rec2020 RGB makes it basically a no-op
# and passes through camera RGB values.
DARKTABLE_TCA_SIDECAR = '''<?xml version="1.0" encoding="UTF-8"?>
<x:xmpmeta xmlns:x="adobe:ns:meta/" x:xmptk="XMP Core 4.4.0-Exiv2">
 <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">
  <rdf:Description rdf:about=""
    xmlns:exif="http://ns.adobe.com/exif/1.0/"
    xmlns:xmp="http://ns.adobe.com/xap/1.0/"
    xmlns:xmpMM="http://ns.adobe.com/xap/1.0/mm/"
    xmlns:darktable="http://darktable.sf.net/"
   exif:DateTimeOriginal="2017:09:30 20:09:00"
   xmp:Rating="1"
   xmpMM:DerivedFrom="tca.img"
   darktable:xmp_version="3"
   darktable:raw_params="0"
   darktable:auto_presets_applied="1"
   darktable:history_end="5"
   darktable:iop_order_version="2">
   <darktable:masks_history>
    <rdf:Seq/>
   </darktable:masks_history>
   <darktable:history>
    <rdf:Seq>
     <rdf:li
      darktable:num="0"
      darktable:operation="basecurve"
      darktable:enabled="0"
      darktable:modversion="6"
      darktable:params="gz09eJxjYICAL3eYbKcsErU1fXPdVmRLpl1B+T07pyon+6WC0fb9R6rtGRgaoHgUDCXAhsRmwpBFxCkAufUQ3Q=="
      darktable:multi_name=""
      darktable:multi_priority="0"
      darktable:iop_order="23.0000000000000"
      darktable:blendop_version="9"
      darktable:blendop_params="gz11eJxjYGBgkGAAgRNODGiAEV0AJ2iwh+CRyscOAAdeGQQ="/>
     <rdf:li
      darktable:num="1"
      darktable:operation="sharpen"
      darktable:enabled="0"
      darktable:modversion="1"
      darktable:params="000000400000003f0000003f"
      darktable:multi_name=""
      darktable:multi_priority="0"
      darktable:iop_order="53.0000000000000"
      darktable:blendop_version="9"
      darktable:blendop_params="gz11eJxjYGBgkGAAgRNODGiAEV0AJ2iwh+CRyscOAAdeGQQ="/>
     <rdf:li
      darktable:num="2"
      darktable:operation="highlights"
      darktable:enabled="0"
      darktable:modversion="2"
      darktable:params="000000000000803f00000000000000000000803f"
      darktable:multi_name=""
      darktable:multi_priority="0"
      darktable:iop_order="4.0000000000000"
      darktable:blendop_version="9"
      darktable:blendop_params="gz11eJxjYGBgkGAAgRNODGiAEV0AJ2iwh+CRyscOAAdeGQQ="/>
     <rdf:li
      darktable:num="3"
      darktable:operation="colorin"
      darktable:enabled="1"
      darktable:modversion="6"
      darktable:params="gz48eJxjYRgFowABWAbaAaNgwAEAHHQACQ=="
      darktable:multi_name=""
      darktable:multi_priority="0"
      darktable:iop_order="27.0000000000000"
      darktable:blendop_version="9"
      darktable:blendop_params="gz11eJxjYGBgkGAAgRNODGiAEV0AJ2iwh+CRyscOAAdeGQQ="/>
     <rdf:li
      darktable:num="4"
      darktable:operation="colorout"
      darktable:enabled="1"
      darktable:modversion="5"
      darktable:params="gz35eJxjYRgFo4CBAQAKKAAF"
      darktable:multi_name=""
      darktable:multi_priority="0"
      darktable:iop_order="58.0000000000000"
      darktable:blendop_version="9"
      darktable:blendop_params="gz11eJxjYGBgkGAAgRNODGiAEV0AJ2iwh+CRyscOAAdeGQQ="/>
    </rdf:Seq>
   </darktable:history>
  </rdf:Description>
 </rdf:RDF>
</x:xmpmeta>
'''

# Sidecar for vignetting corrections
# * disable basecurve
# * disable shapren
# * disable highlight reconstruction
# * set colorin to camera color matrix
# * set colorin working space to Linear Rec2020 RGB
# * set colorout to Linear Rec2020 RGB
DARKTABLE_VIGNETTING_SIDECAR = '''<?xml version="1.0" encoding="UTF-8"?>
<x:xmpmeta xmlns:x="adobe:ns:meta/" x:xmptk="XMP Core 4.4.0-Exiv2">
 <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">
  <rdf:Description rdf:about=""
    xmlns:exif="http://ns.adobe.com/exif/1.0/"
    xmlns:xmp="http://ns.adobe.com/xap/1.0/"
    xmlns:xmpMM="http://ns.adobe.com/xap/1.0/mm/"
    xmlns:darktable="http://darktable.sf.net/"
   exif:DateTimeOriginal="2017:09:30 20:09:00"
   xmp:Rating="1"
   xmpMM:DerivedFrom="vignetting.img"
   darktable:xmp_version="3"
   darktable:raw_params="0"
   darktable:auto_presets_applied="1"
   darktable:history_end="5"
   darktable:iop_order_version="2">
   <darktable:masks_history>
    <rdf:Seq/>
   </darktable:masks_history>
   <darktable:history>
    <rdf:Seq>
     <rdf:li
      darktable:num="0"
      darktable:operation="basecurve"
      darktable:enabled="0"
      darktable:modversion="6"
      darktable:params="gz09eJxjYICAL3eYbKcsErU1fXPdVmRLpl1B+T07pyon+6WC0fb9R6rtGRgaoHgUDCXAhsRmwpBFxCkAufUQ3Q=="
      darktable:multi_name=""
      darktable:multi_priority="0"
      darktable:iop_order="23.0000000000000"
      darktable:blendop_version="9"
      darktable:blendop_params="gz11eJxjYGBgkGAAgRNODGiAEV0AJ2iwh+CRyscOAAdeGQQ="/>
     <rdf:li
      darktable:num="1"
      darktable:operation="sharpen"
      darktable:enabled="0"
      darktable:modversion="1"
      darktable:params="000000400000003f0000003f"
      darktable:multi_name=""
      darktable:multi_priority="0"
      darktable:iop_order="53.0000000000000"
      darktable:blendop_version="9"
      darktable:blendop_params="gz11eJxjYGBgkGAAgRNODGiAEV0AJ2iwh+CRyscOAAdeGQQ="/>
     <rdf:li
      darktable:num="2"
      darktable:operation="highlights"
      darktable:enabled="0"
      darktable:modversion="2"
      darktable:params="000000000000803f00000000000000000000803f"
      darktable:multi_name=""
      darktable:multi_priority="0"
      darktable:iop_order="4.0000000000000"
      darktable:blendop_version="9"
      darktable:blendop_params="gz11eJxjYGBgkGAAgRNODGiAEV0AJ2iwh+CRyscOAAdeGQQ="/>
     <rdf:li
      darktable:num="3"
      darktable:operation="colorout"
      darktable:enabled="1"
      darktable:modversion="5"
      darktable:params="gz35eJxjYRgFo4CBAQAKKAAF"
      darktable:multi_name=""
      darktable:multi_priority="0"
      darktable:iop_order="58.0000000000000"
      darktable:blendop_version="9"
      darktable:blendop_params="gz11eJxjYGBgkGAAgRNODGiAEV0AJ2iwh+CRyscOAAdeGQQ="/>
     <rdf:li
      darktable:num="4"
      darktable:operation="colorin"
      darktable:enabled="1"
      darktable:modversion="6"
      darktable:params="gz48eJzjZhgFowABWAbaAaNgwAEAOQAAEA=="
      darktable:multi_name=""
      darktable:multi_priority="0"
      darktable:iop_order="27.0000000000000"
      darktable:blendop_version="9"
      darktable:blendop_params="gz11eJxjYGBgkGAAgRNODGiAEV0AJ2iwh+CRyscOAAdeGQQ="/>
    </rdf:Seq>
   </darktable:history>
  </rdf:Description>
 </rdf:RDF>
</x:xmpmeta>
'''

# -----------------------------------------------------------------------------------
# from stackoverflow.com/questions/3056048/filename-and-line-number-of-python-script
# and https://thepythoncode.com/article/print-variable-name-and-value-in-python (=>python3.8)

def debug_print_out(message='', data=None):
    from sys import _getframe
    print(f'\nline {_getframe().f_back.f_lineno}: {message}', data)
    
# prints line number at the start of a string or list of variable and it's type
# where
    # print('data and tag', data, tag)
    # debug_print_out('data and tag', [data, tag])
# and
    # print('data is ', type(data), data)
    # debug_print_out('', [f'{data=}', type(data)])
# -----------------------------------------------------------------------------------

def get_max_worker_count():
    # --------------------------------
    # debug_print_out('get_max-worker-count function','')
    # --------------------------------
    max_workers = int(multiprocessing.cpu_count() / 2)

    if max_workers < 1:
        return 1

    return max_workers
    
def is_raw_file(filename):
    # --------------------------------
    # debug_print_out('is_raw_file function', '')
    # --------------------------------
    raw_file_extensions = [
            ".3FR", ".ARI", ".ARW", ".BAY", ".CRW", ".CR2", ".CAP", ".DCS",
            ".DCR", ".DNG", ".DRF", ".EIP", ".ERF", ".FFF", ".IIQ", ".K25",
            ".KDC", ".MEF", ".MOS", ".MRW", ".NEF", ".NRW", ".OBM", ".ORF",
            ".PEF", ".PTX", ".PXN", ".R3D", ".RAF", ".RAW", ".RWL", ".RW2",
            ".RWZ", ".SR2", ".SRF", ".SRW", ".X3F", ".JPG", ".JPEG", ".TIF",
            ".TIFF",
        ]
    file_ext = os.path.splitext(filename)[1]

    return file_ext.upper() in raw_file_extensions

def has_exif_tag(data, tag):
    # --------------------------------
    # debug_print_out('has_exif_tag function', '')
    # debug_print_out('data and tag', [data, tag])
    # --------------------------------
    return tag in data

def image_read_exif(filename):
    # --------------------------------
    # debug_print_out('image_read_exif function on ', filename)
    # --------------------------------
    focal_length = 0.0
    aperture = 0.0



    data = ImageMetadata(filename)
    # This reads the metadata and closes the file
    data.read()

    # ----------------------------------------------------------
    # debug_print_out('', [f'{data=}', type(data)])
    # added aspect ratio for Olympus
    aspect_ratio = None
    tag = 'Exif.OlympusIp.AspectRatio'
    if has_exif_tag(data, tag):
        aspect_ratio = data[tag].human_value
        # debug_print_out('', [f'{aspect_ratio=}', type(aspect_ratio)])
    else:
        print(filename, ' has no exif available')
    # -----------------------------------------------------------------------

    lens_model = None
    tag = 'Exif.Photo.LensModel'
    if has_exif_tag(data, tag):
        lens_model = data[tag].value
        # ----------------------------------------------------------------
        # debug_print_out('', [f'{lens_model=}', type(lens_model)])
        # ----------------------------------------------------------------
    else:
        tag = 'Exif.NikonLd3.LensIDNumber'
        if has_exif_tag(data, tag):
            lens_model = data[tag].human_value

        tag = 'Exif.Panasonic.LensType'
        if has_exif_tag(data, tag):
            lens_model = data[tag].value

        tag = 'Exif.Sony1.LensID'
        if has_exif_tag(data, tag):
            lens_model = data[tag].human_value

        tag = 'Exif.Minolta.LensID'
        if has_exif_tag(data, tag):
            lens_model = data[tag].human_value
        
        # --------------------------------------------------------    
        # added Olympus lens type
        # eg Exif.OlympusEq.LensType = Olympus Zuiko Digital 11-22mm F2.8-3.5
        #    Exif.OlympusEq.LensModel = OLYMPUS 11-22mm Lens
        #    Composite.LensID = Olympus Zuiko Digital 11-22mm F2.8-3.5
        # For a legacy manual lens all of these Exif.OlympusEq.LensType = None
        #                                       Composite.LensID = None
        #                                       Exif.OlympusEq.LensModel = {not set}
        # debug_print_out('', [f'{lens_model=}', type(lens_model)])
        tag = 'Exif.OlympusEq.LensType'
        # or tag = 'Exif.OlympusEq.LensModel'
        if has_exif_tag(data, tag):
            lens_model = data[tag].human_value
            # debug_print_out('', [f'{lens_model=}', type(lens_model)])
        # ---------------------------------------------------------    

    if lens_model is None:
       lens_model = 'Standard'

    tag = 'Exif.Photo.FocalLength'
    if has_exif_tag(data, tag):
        focal_length = float(data[tag].value)
        # ---------------------------------------------
        # debug_print_out('', [f'{focal_length=}', type(focal_length)])
        # ---------------------------------------------
    else:
        print("%s doesn't have Exif.Photo.FocalLength set. " % (filename) +
              "Please fix it manually.")

    tag = 'Exif.Photo.FNumber'
    if has_exif_tag(data, tag):
        aperture = float(data[tag].value)
        # ---------------------------------------------
        # debug_print_out('', [f'{aperture=}', type(aperture)])
        # ---------------------------------------------
    else:
        print("%s doesn't have Exif.Photo.FNumber set. " % (filename) +
              "Please fix it manually.")

    # ----------------------------------------------------------------
    # for legacy lenses that generate no meta data
    # Olympus cameras add (exiv style)
    #       Exif.Photo.FocalLength=0.0 mm
    #       Exif.Photo.FNumber=0
    #       OlympusEq.LensType=None
    #       OlympusEq.LensModel={empty}
    #       Exif.Photo.LensModel does not exist though is available
    # It is considered risky to alter makernotes such as OlympusEq with exiftool and only Exif.Photo.LensModel is available
    if aperture == 0:
        print("\nLens metadata not found. Is the lens legacy manual?")
        print("Please add metadata with:")
        print("exiftool -Exif:LensModel='long lens model name' -Exif:FocalLength='00.0 mm' -Exif:FNumber='0' filename.ext")
        print("eg:")
        print("exiftool -Exif:LensModel='Olympus OM System ZUIKO Auto-S 50mm F1:1.8' -Exif:FocalLength='50.0 mm' -Exif:FNumber='8' PC294201.ORF")
    # ----------------------------------------------------------------
    
    # -----------------------------------------------------------------
    #python3-exiv2 doesnt find scalefactor35mmequivalent tag in composite (keyErrror on composite)

    #scale_factor = None
    #print('scale_factor is', type(scale_factor), scale_factor)
    #tag = 'Exif.Composite.ScaleFactor35efl'
    #if has_exif_tag(data, tag):
        #scale_factor = data[tag].human_value
        #print('data is ', type(data), data)
        #print('data[] is ', type(data['composite']), data['composite'])
        #print('scale_factor is', type(scale_factor), scale_factor)
    #else:
        #print('***no exif available')
    
    #exiftool -T -Composite:ScaleFactor35efl ./distortion/*  returns 2.0 from command line but not here can't handle the wild card
    #from https://stackoverflow.com/a/75782026

    crop_factor = None
    cmd = [ "exiftool", "-T", "-scalefactor*", filename]        # "./distortion/"
    output = subprocess.run(cmd, capture_output=True)
    # # debug_print_out('exiftool', [f'{output=}', type(output)])
    # # debug_print_out('', [f'{output.returncode=}', type(output.returncode)])
    if output.returncode != 0:
        print('exiftool error ', output.stderr)
        crop_factor = 0.0
    else:
        import json
        crop_factor = json.loads(output.stdout)
        # # debug_print_out('', [f'{output.stdout=}', type(output.stdout)])
        # # debug_print_out('', [f'{json.loads(output.stdout)=}', type(json.loads(output.stdout))])
        # json = JavaScript Object Notation library must be imported before use
        # loads is used to decode json data
        # print('crop factor is ',type(crop_factor), crop_factor)
        # print(type(crop_factor), f'{crop_factor=}')
        # # debug_print_out('', [f'{crop_factor=}', type(crop_factor)])
    
    # ----------------------------------------------------------------------------------------------
    
    # ----------------------------------------------------------------------------------------------
    # lens maker for olympus is "Olympus Zuiko Digital" from OlympusEq.LensType = "Olympus Zuiko Digital 11-22mm F2.8-3.5"
    # if Exif.Photo.LensModel has been added for manual legacy lens use that

    lens_maker = None
    # # debug_print_out('', [f'{lens_maker=}',  type(lens_maker)])

    tag_list = ['Exif.Photo.LensModel', 'Exif.OlympusEq.LensType']
    # # debug_print_out('', [f'{tag_list=}', type(tag_list)])
    for tag in tag_list:
        # # debug_print_out('', [f'{tag=}', type(tag)])
        if has_exif_tag(data, tag):
            # debug_print_out('', [f'{tag=}', type(tag)])
            # debug_print_out('', [f'{data[tag]=}', type(data[tag])])
            # debug_print_out('', [f'{data[tag].human_value=}', type(data[tag].human_value)])
            lens_maker = data[tag].human_value
            if 'Olympus Zuiko Digital' in data[tag].human_value:
                lens_maker = 'Olympus Zuiko Digital'
            if 'Olympus OM System' in data[tag].human_value:
                lens_maker = 'Olympus Zuiko OM System'
            if data[tag].human_value == 'None':     # Olympus camera creates the metadata 'Exif.OlympusEq.LensType' = [None] for legacy manual lens
                lens_maker = '[unknown}'
            # debug_print_out('', [f'{lens_maker=}', type(lens_maker)])
            break                                   # break out of the for loop if lens_maker is assinged a value
        else:
            print('***no exif available')
            lens_maker = '[unknown]'

    # ----------------------------------------------------------------------------------------------
    # ----------------------------------------------------------------------------------------------
    # mount for Olympus Zuiko Digital lenses is 4/3 System

    mount = None
    if lens_maker == '[unknown}':
        print('no exif available')
        mount = '[unknown]'
    else:
        if lens_maker == 'Olympus Zuiko Digital':
            mount = '4/3 System'
        if lens_maker == 'Olympus Zuiko OM System':
            mount = 'Olympus OM'
        # debug_print_out('', [f'{mount=}', type(mount)])
    # ----------------------------------------------------------------------------------------------
    
    return { "lens_model" : lens_model,
             "focal_length" : focal_length,
             "aperture" : aperture,
             # ---------------------------------
             'aspect_ratio' : aspect_ratio,
             'crop_factor' : crop_factor,
             'lens_maker' : lens_maker,
             'mount' : mount}
             # returns variables as a 'dict' class (similar to an array) into the variable exif_data in run_distortion function
             # ---------------------------------

def write_sidecar_file(sidecar_file, content):
    # --------------------------------
    # debug_print_out('write_sidecar_file function', '')
    # --------------------------------
    if not os.path.isfile(sidecar_file):
        try:
            with open(sidecar_file, 'w') as f:
                f.write(content)
        except OSError:
            return False

    return True

# convert raw file to 16bit tiff
def convert_raw_for_distortion(input_file, sidecar_file, output_file=None):
    # --------------------------------
    # debug_print_out('convert_raw_for_distortion function', '')
    # --------------------------------
    if output_file is None:
        output_file = ("%s.tif" % os.path.splitext(input_file)[0])

    if not os.path.exists(output_file):
        print("Converting %s to %s ..." % (input_file, output_file), flush=True)

        with tempfile.TemporaryDirectory(prefix="lenscal_") as dt_tmp_dir:
            dt_log_path = os.path.join(dt_tmp_dir, "dt.log")

            with open(dt_log_path, 'w') as dt_log_file:
                cmd = [
                        "darktable-cli",
                        input_file,
                        sidecar_file,
                        output_file,
                        "--core",
                        "--configdir", dt_tmp_dir,
                        "--conf", "plugins/lighttable/export/iccintent=0", # perceptual
                        "--conf", "plugins/lighttable/export/iccprofile=sRGB",
                        "--conf", "plugins/lighttable/export/style=none",
                        "--conf", "plugins/imageio/format/tiff/bpp=16",
                        "--conf", "plugins/imageio/format/tiff/compress=5"
                    ]

                try:
                    subprocess.check_call(cmd, stdout=dt_log_file, stderr=subprocess.STDOUT)
                except subprocess.CalledProcessError:
                    with open(dt_log_path, 'r') as fin:
                        print(fin.read())
                    raise
                except OSError:
                    print("Could not find darktable-cli")
                    return None

    return output_file

def convert_raw_for_tca(input_file, sidecar_file, output_file=None):
    # --------------------------------
    # debug_print_out('convert_raw_for_tca function','')
    # --------------------------------
    if output_file is None:
        output_file = ("%s.ppm" % os.path.splitext(input_file)[0])

    if not os.path.exists(output_file):
        with tempfile.TemporaryDirectory(prefix="lenscal_") as dt_tmp_dir:
            dt_log_path = os.path.join(dt_tmp_dir, "dt.log")

            with open(dt_log_path, 'w') as dt_log_file:
                cmd = [
                        "darktable-cli",
                        input_file,
                        sidecar_file,
                        output_file,
                        "--core",
                        "--configdir", dt_tmp_dir,
                        "--conf", "plugins/lighttable/export/iccprofile=image",
                        "--conf", "plugins/lighttable/export/style=none",
                    ]

                try:
                    subprocess.check_call(cmd, stdout=dt_log_file, stderr=subprocess.STDOUT)
                except subprocess.CalledProcessError:
                    with open(dt_log_path, 'r') as fin:
                        print(fin.read())
                    raise
                except OSError:
                    print("Could not find darktable-cli")

    return output_file

def convert_raw_for_vignetting(input_file, sidecar_file, output_file=None):
    # --------------------------------
    # debug_print_out('convert_raw_for_vignetting function', '')
    # --------------------------------
    if output_file is None:
        output_file = ("%s.ppm" % os.path.splitext(input_file)[0])

    if not os.path.exists(output_file):
        with tempfile.TemporaryDirectory(prefix="lenscal_") as dt_tmp_dir:
            dt_log_path = os.path.join(dt_tmp_dir, "dt.log")

            with open(dt_log_path, 'w') as dt_log_file:
                cmd = [
                        "darktable-cli",
                        input_file,
                        sidecar_file,
                        output_file,
                        "--width", "250",
                        "--core",
                        "--configdir", dt_tmp_dir,
                        "--conf", "plugins/lighttable/export/iccprofile=image",
                        "--conf", "plugins/lighttable/export/style=none",
                    ]

                try:
                    subprocess.check_call(cmd, stdout=dt_log_file, stderr=subprocess.STDOUT)
                except subprocess.CalledProcessError:
                    with open(dt_log_path, 'r') as fin:
                        print(fin.read())
                    raise
                except OSError:
                    print("Could not find darktable-cli")

    return output_file

def convert_ppm_for_vignetting(input_file):
    # --------------------------------
    # debug_print_out('convert_ppm_for_vignetting function', '')
    # --------------------------------
    output_file = ("%s.pgm" % os.path.splitext(input_file)[0])

    # Convert the ppm file to a pgm (grayscale) file
    if not os.path.exists(output_file):
        cmd = [ "convert",
                "-colorspace",
                "RGB",
                input_file,
                "-set",
                "colorspace",
                "RGB",
                output_file ]
        try:
            subprocess.check_call(cmd, stdout=DEVNULL, stderr=subprocess.STDOUT)
        except subprocess.CalledProcessError:
            raise
        except OSError:
            print("Could not find convert")

    return output_file

def plot_pdf(plot_file):
    # --------------------------------
    # debug_print_out('plot_pdf function', '')
    # --------------------------------
    try:
        gnuplot = shutil.which("gnuplot")
    except shutil.Error:
        return False

    cmd = [ gnuplot, plot_file ]
    try:
        subprocess.check_call(cmd, stdout=DEVNULL, stderr=subprocess.STDOUT)
    except subprocess.CalledProcessError:
        raise
    except OSError:
        print("Could not find gnuplot")
        return False

    return True

def merge_final_pdf(final_pdf, pdf_dir):
    # --------------------------------
    # debug_print_out('merge_final_pdf function', '')
    # --------------------------------


    # --------------------------------------------------------------------------------------------------------------
    # PyPDF2.errors.DeprecationError: PdfFileMerger is deprecated and was removed in PyPDF2 3.0.0. Use PdfMerger instead
    # pdf_merger = PdfFileMerger()
    # --------------------------------------------------------------------------------------------------------------
    
    pdf_merger = PdfMerger()

    pdf_files = []

    for path, directories, files in os.walk(pdf_dir):
        for filename in files:
            if os.path.splitext(filename)[1] != '.pdf':
                continue

            pdf_files.append(filename)

    if len(pdf_files) == 0:
        return

    pdf_files.sort()

    for pdf in pdf_files:
        pdf_merger.append(os.path.join(pdf_dir, pdf))

    pdf_merger.write(final_pdf)
    pdf_merger.close()

# -------------------------------------------------------------
# not needed done to prove to myself structure of lenses_exif_group in create_lenses_config function
#
# def search_dict_f(search_query, search_data):
#    # debug_print_out('search_dict_f function', '')
#    counter = 0
#    for key1 in search_data:
#        search_result = key1[search_query]
#        print('loop', counter)
#        debug_print_out('', [f'{key1=}', type(key1)]) # type is a dict
#        debug_print_out('', [f'{search_data=}', type(search_data)]) # type is a list of two dictionaries
#        debug_print_out('', [f'{key1[search_query]=}', type(key1[search_query])]) #type is a str
#        debug_print_out('', [f'{search_data[counter][search_query]=}', type(search_data[counter][search_query])]) #type is a str
#        debug_print_out('', [f'{search_result=}', type(search_result)]) #type is a str
#        counter = counter + 1
#        if search_query in key1:
#            break
# loops through search_data list untill key matching search_query is found
# alternativeley as search_data is a list just access the 1st item in the list
#    debug_print_out(''. [f'{search_data[0][search_query]=}', type(search_data[0][search_query])])

#    return search_result
# -------------------------------------------------------------

def create_lenses_config(lenses_exif_group):
    # --------------------------------
    # debug_print_out('create_lenses_config function', '')
    # debug_print_out('', [f'{lenses_exif_group=}', type(lenses_exif_group)]) # type is a dict, actually a {dictionary} of a [list] of {dictionaries}?)
    # debug_print_out('', [f'{lenses_exif_group.keys()=}', type(lenses_exif_group.keys)])
    # debug_print_out('', [f'{lenses_exif_group.values()=}', type(lenses_exif_group.values)])
    # debug_print_out('', [f'{lenses_exif_group.items()=}', type(lenses_exif_group.items)])
    # --------------------------------
    config = configparser.ConfigParser()
    for lenses in lenses_exif_group:
        # --------------------------------------------------------------
        # debug_print_out('', [f'{lenses=}', type(lenses)])
        # debug_print_out('the first image listed is ', [f"{lenses_exif_group[lenses][0]['aspect_ratio']=}", type(lenses_exif_group[lenses][0]['aspect_ratio'])])
        # -------------------------------------------------------------

        config[lenses] = {
                # ----------------------------------------
                #'maker' : '[unknown]',
                'maker' : lenses_exif_group[lenses][0]['lens_maker'],
                #'mount' : '[unknown]',
                'mount' : lenses_exif_group[lenses][0]['mount'],
                #'cropfactor' : '1.0',
                'cropfactor' : lenses_exif_group[lenses][0]['crop_factor'],
                #'aspect_ratio' : '3:2',
                #'aspect_ratio' : search_dict_f('aspect_ratio', lenses_exif_group[lenses]),
                'aspect_ratio' : lenses_exif_group[lenses][0]['aspect_ratio'],
                # ----------------------------------------
                'type' : 'normal'
                }
        for exif_data in lenses_exif_group[lenses]:
            distortion = ("distortion(%.1fmm)" % exif_data['focal_length'])
            config[lenses][distortion] = '0.0, 0.0, 0.0'
    with open('lenses.conf', 'w') as configfile:
        config.write(configfile)

    print("A template has been created for distortion corrections as lenses.conf.")
    print("Please fill this file with proper information. The most important")
    print("values are:")
    print("")
    print("maker:        is the manufacturer or the lens, e.g. 'FE 16-35mm F2.8 GM'")
    print("mount:        is the name of the mount system, e.g. 'Sony E'")
    print("cropfactor:   is the crop factor of the camera as a float, e.g. '1.0' for")
    print("              full frame")
    print("aspect_ratio: is the aspect_ratio, e.g. '3:2'")
    print("type:         is the type of the lens, e.g. 'normal' for rectilinear")
    print("              lenses. Other possible values are: stereographic, equisolid,")
    print("              stereographic, panoramic or fisheye.")
    print("")
    print("You can find details for distortion calculations here:")
    print("")
    print("https://pixls.us/articles/create-lens-calibration-data-for-lensfun/")

    return

def parse_lenses_config(filename):
    # --------------------------------
    # debug_print_out('parse_lenses_config function', '')
    # --------------------------------
    config = configparser.ConfigParser()
    config.read(filename)

    lenses = {}

    for section in config.sections():
        lenses[section] = {}
        lenses[section]['distortion'] = {}
        lenses[section]['tca'] = {}
        lenses[section]['vignetting'] = {}

        for key in config[section]:
            if key.startswith('distortion'):
                # ------------------------------------------------
                # line in config file eg distortion(7.0mm) = 0.0, 0.0, 0.0
                # debug_print_out('', [f'{key=}', type(key)])     # is <class 'str'> distortion(7.0mm)
                # debug_print_out('', [f"{key.startswith('distortion')=}", type(key.startswith('distortion'))])  # is  <class 'bool'> True
                # uses nested " '' " quotes
                # debug_print_out('', [f'{key[11:len(key)]=}', type(key[11:len(key)])])
                # debug_print_out('', [f'{key[11:len(key) - 3]=}', type(key[11:len(key) - 3])])
                # test if key starts with distortion then exclude first 11 characters eg distortion( 
                # and then remove last 3 characters eg mm)
                # result is 7.0
                # ------------------------------------------------
                focal_length = key[11:len(key) - 3]
                # -------------------------------------------------------------
                # debug_print_out('', [f'{focal_length=}', type(focal_length)])
                # -------------------------------------------------------------
                lenses[section]['distortion'][focal_length] = config[section][key]
            else:
                lenses[section][key] = config[section][key]
    # -------------------------------------------------
    # debug_print_out('', [f'{lenses=}', type(lenses)])
    # -------------------------------------------------
    return lenses

def tca_correct(input_file, original_file, exif_data, complex_tca=False):
    # --------------------------------
    # debug_print_out('tca_correct function', '')
    # --------------------------------
    basename = os.path.splitext(input_file)[0]
    output_file = ("%s.tca" % basename)
    gp_filename = ("%s.gp" % basename)
    pdf_filename = ("%s.pdf" % basename)

    if not os.path.exists(output_file):
        print("Running TCA corrections for %s ..." % (input_file), flush=True)

        tca_complexity = 'v'
        if complex_tca:
            tca_complexity = 'bv'
        cmd = [ "tca_correct", "-o", tca_complexity, input_file ]
        try:
            output = subprocess.check_output(cmd, stderr=DEVNULL)
        except subprocess.CalledProcessError:
            raise
        except OSError:
            print("Could not find tca_correct")
            return None

# -----------------------------------------------------------------------
# I've got the flatpak Hugin as it's not on the Ubuntu 20.04LTS repositories
# tca_correct required extracted from Hugin source
# and placed in /usr/bin/
# libhuginbase.so.0.0 extracted from Hugin source
# and placed in /usr/local/lib/hugin/
# ----------------------------------------------------------------------

        tca_data_match = re.match(r"-r [.0]+:(?P<br>[-.0-9]+):[.0]+:(?P<vr>[-.0-9]+) -b [.0]+:(?P<bb>[-.0-9]+):[.0]+:(?P<vb>[-.0-9]+)",
                            output.decode('ascii'))
        if tca_data_match is None:
            print("Could not find tca correction data")
            return None

        tca_data = tca_data_match.groupdict()

        tca_config = configparser.ConfigParser()
        tca_config[exif_data['lens_model']] = {
                'focal_length' : exif_data['focal_length'],
                'complex_tca' : complex_tca,
                'tca' : output.decode('ascii'),
                'br' : tca_data['br'],
                'vr' : tca_data['vr'],
                'bb' : tca_data['bb'],
                'vb' : tca_data['vb'],
                }
        with open(output_file, "w") as tcafile:
            tca_config.write(tcafile)

        if complex_tca:
            with codecs.open(gp_filename, "w", encoding="utf-8") as c:
                c.write('set term pdf\n')
                c.write('set print "%s"\n' % (input_file))
                c.write('set output "%s"\n' % (pdf_filename))
                c.write('set fit logfile "/dev/null"\n')
                c.write('set grid\n')
                c.write('set title "%s, %0.1f mm, f/%0.1f\\n%s" noenhanced\n' %
                        (exif_data['lens_model'],
                         exif_data['focal_length'],
                         exif_data['aperture'],
                         original_file))
                c.write('plot [0:1.8] %s * x**2 + %s title "red", %s * x**2 + %s title "blue"\n' %
                        (tca_data['br'], tca_data["vr"], tca_data["bb"], tca_data["vb"]))

            plot_pdf(gp_filename)

def load_pgm(filename):
    # --------------------------------
    # debug_print_out('load_pgm function', '')
    # --------------------------------
    header = None
    width = None
    height = None
    maxval = None

    with open(filename, 'rb') as f:
        buf = f.read()
    try:
        header, width, height, maxval = re.search(
            b"(^P5\s(?:\s*#.*[\r\n])*"
            b"(\d+)\s(?:\s*#.*[\r\n])*"
            b"(\d+)\s(?:\s*#.*[\r\n])*"
            b"(\d+)\s(?:\s*#.*[\r\n]\s)*)", buf).groups()
    except AttributeError:
        raise ValueError("Not a NetPGM file: '%s'" % filename)

    f.close()

    width = int(width)
    height = int(height)
    maxval = int(maxval)

    if maxval == 255:
        dt = np.dtype(np.uint8)
    elif maxval == 65535:
        dt = np.dtype(np.uint16)
    elif maxval == 4294967295:
        dt = np.dtype(np.float32)
    else:
        raise ValueError("Not a NetPGM file: '%s'" % filename)
    dt = dt.newbyteorder('B')

    shape = np.frombuffer(buf,
                          dtype = dt,
                          count = width * height,
                          offset = len(header))

    return width, height, shape.reshape((height, width))

def fit_function(radius, A, k1, k2, k3):
    # --------------------------------
    # debug_print_out('fit_function function', '')
    # --------------------------------
    return A * (1 + k1 * radius**2 + k2 * radius**4 + k3 * radius**6)

def calculate_vignetting(input_file, original_file, exif_data, distance):
    # --------------------------------
    # debug_print_out('calculate_vignetting function', '')
    # --------------------------------
    basename = os.path.splitext(input_file)[0]
    all_points_filename = ("%s.all_points.dat" % basename)
    bins_filename = ("%s.bins.dat" % basename)
    pdf_filename = ("%s.pdf" % basename)
    gp_filename = ("%s.gp" % basename)
    vig_filename = ("%s.vig" % basename)

    if os.path.exists(vig_filename):
        return

    print("Generating vignetting data for %s ... " % input_file, flush=True)

    # This loads the pgm file and we get the image data and an one dimensional array
    # image_data = [1009, 1036, 1071, 1106, 1140, 1169, 1202, 1239, ...]
    width, height, image_data = load_pgm(input_file)

    # Get the half diagonal of the image
    half_diagonal = math.hypot(width // 2, height // 2)
    maximal_radius = 1

    # Only remember pixel intensities which are in the given radius
    radii, intensities = [], []
    for y in range(image_data.shape[0]):
        for x in range(image_data.shape[1]):
            radius = math.hypot(x - width // 2, y - height // 2) / half_diagonal
            if radius <= maximal_radius:
                radii.append(radius)
                intensities.append(image_data[y,x])

    with open(all_points_filename, 'w') as f:
        for radius, intensity in zip(radii, intensities):
            f.write("%f %d\n" % (radius, intensity))

    number_of_bins = 16
    bins = [[] for i in range(number_of_bins)]
    for radius, intensity in zip(radii, intensities):
        # The zeroth and the last bin are only half bins which means that their
        # means are skewed.  But this is okay: For the zeroth, the curve is
        # supposed to be horizontal anyway, and for the last, it underestimates
        # the vignetting at the rim which is a good thing (too much of
        # correction is bad).
        bin_index = int(round(radius / maximal_radius * (number_of_bins - 1)))
        bins[bin_index].append(intensity)
    radii = [i / (number_of_bins - 1) * maximal_radius for i in range(number_of_bins)]
    intensities = [np.median(bin) for bin in bins]

    with open(bins_filename, 'w') as f:
        for radius, intensity in zip(radii, intensities):
            f.write("%f %d\n" % (radius, intensity))

    radii, intensities = np.array(radii), np.array(intensities)

    A, k1, k2, k3 = leastsq(lambda p, x, y: y - fit_function(x, *p), [30000, -0.3, 0, 0], args=(radii, intensities))[0]

    vig_config = configparser.ConfigParser()
    vig_config[exif_data['lens_model']] = {
                'focal_length' : exif_data['focal_length'],
                'aperture' : exif_data['aperture'],
                'distance' : distance,
                'A' : ('%.7f' % A),
                'k1' : ('%.7f' % k1),
                'k2' : ('%.7f' % k2),
                'k3' : ('%.7f' % k3),
                }
    with open(vig_filename, "w") as vigfile:
        vig_config.write(vigfile)

    if distance == float("inf"):
        distance = "∞"

    with codecs.open(gp_filename, "w", encoding="utf-8") as c:
        c.write('set term pdf\n')
        c.write('set print "%s"\n' % (input_file))
        c.write('set output "%s"\n' % (pdf_filename))
        c.write('set fit logfile "/dev/null"\n')
        c.write('set grid\n')
        c.write('set title "%s, %0.1f mm, f/%0.1f, %s m\\n%s" noenhanced\n' %
                (exif_data['lens_model'],
                 exif_data['focal_length'],
                 exif_data['aperture'],
                 distance,
                 original_file))
        c.write('plot "%s" with dots title "samples", ' %
                all_points_filename)
        c.write('"%s" with linespoints lw 4 title "average", ' %
                bins_filename)
        c.write('%f * (1 + (%f) * x**2 + (%f) * x**4 + (%f) * x**6) title "fit"\n' %
                (A, k1, k2, k3))

    plot_pdf(gp_filename)

def init():
    # --------------------------------
    # debug_print_out('init function', '')
    # --------------------------------
    # Create directory structure
    dirlist = ['distortion', 'tca', 'vignetting']

    for d in dirlist:
        if os.path.isfile(d):
            print("ERROR: '%s' is a file, can't create directory!" % d)
            return
        elif not os.path.isdir(d):
            os.mkdir(d)

    print("The following directory structure has been created in the "
          "local directory\n\n"
          "1. distortion - Put RAW file created for distortion in here\n"
          "2. tca        - Put chromatic abbrevation RAW files in here\n"
          "3. vignetting - Put RAW files to calculate vignetting in here\n")

def create_distortion_correction(export_path, path, filename, sidecar_file):
    # --------------------------------
    # debug_print_out('create_distortion_correction function', '')
    # --------------------------------
    input_file = os.path.join(path, filename)
    output_file = os.path.join(path, "exported", ("%s.tif" % os.path.splitext(filename)[0]))

    # Convert RAW files to TIF for hugin
    output_file = convert_raw_for_distortion(input_file, sidecar_file, output_file)

    return True

def run_distortion():
    # --------------------------------
    # debug_print_out('run_distortion function', '')
    # --------------------------------
    lenses_config_exists = os.path.isfile('lenses.conf')
    lenses_exif_group = {}

    # clarified message
    print('Running file conversions for hugin distortion corrections ...')

    if not os.path.isdir("distortion"):
        print("No distortion directory, you have to run init first!")
        return

    export_path = os.path.join("distortion", "exported")
    if not os.path.isdir(export_path):
        os.mkdir(export_path)

    sidecar_file = os.path.join(export_path, "distortion.xmp")
    if not write_sidecar_file(sidecar_file, DARKTABLE_DISTORTION_SIDECAR):
        print("Failed to write sidecar_file: %s" % sidecar_file)
        return

    # Parse EXIF data
    for path, directories, files in os.walk('distortion'):
        for filename in files:
            if path != "distortion":
                continue
            if not is_raw_file(filename):
                continue

            input_file = os.path.join(path, filename)

            exif_data = image_read_exif(input_file)
            # -----------------------------------------------------------------------
            # exif_data variable becomes a type 'dict' of array containing meta data from function image_read_exif
            # debug_print_out('', [f'{exif_data=}', type(exif_data)])
            # debug_print_out('', [f"{exif_data['aspect_ratio']=}", type(exif_data['aspect_ratio'])])
            # -----------------------------------------------------------------------
            
            if exif_data is not None:
                if exif_data['lens_model'] not in lenses_exif_group:
                    lenses_exif_group[exif_data['lens_model']] = []
                  
                    #---------------------------------------------------------------------------------------
                    # creates new key named from the exif_data[lens_model] value if it does not already exist
                    # debug_print_out('1)', [f'{lenses_exif_group=}', type(lenses_exif_group)])
                    # --------------------------------------------------------------------------------------
                    
                lenses_exif_group[exif_data['lens_model']].append(exif_data)

                # ------------------------------------------------------------------------
                # put entire exif_data dict into lenses_exif_group key named after exif_data['lens_model'] value
                # essentially same as
                # lenses_exif_group = {exif_data['lens_model'] : exif_data}
                # but appends new entry for every image rather than overwriting
                # debug_print_out('2)', [f'{lenses_exif_group=}', type(lenses_exif_group)])
                # lenses_exif_group is a dictionary of lists    
                #-------------------------------------------------------------------------
                
                # Add focal length to file name for easier identification
                if exif_data['focal_length'] > 1.0:
                    output_file = os.path.join(path, "exported", ("%s_%dmm.tif" % (os.path.splitext(filename)[0], exif_data['focal_length'])))

    # Create TIFF for hugin
    with concurrent.futures.ProcessPoolExecutor(max_workers=get_max_worker_count()) as executor:
        result_futures = []

        for path, directories, files in os.walk('distortion'):
            for filename in files:
                if path != "distortion":
                    continue
                if not is_raw_file(filename):
                    continue
                future = executor.submit(create_distortion_correction, export_path, path, filename, sidecar_file)
                result_futures.append(future)

        for f in concurrent.futures.as_completed(result_futures):
            if f.result():
                print("OK")

    if not lenses_config_exists:
        sorted_lenses_exif_group = {}
        for lenses in sorted(lenses_exif_group):
            # TODO: Remove duplicates?
            sorted_lenses_exif_group[lenses] = sorted(lenses_exif_group[lenses], key=lambda exif : exif['focal_length'])
            
            # ---------------------------------
            # sort the items by key = focal length
            # lambda is an anonymous funtion?
            # ---------------------------------

        create_lenses_config(sorted_lenses_exif_group)

def create_tca_correction(export_path, path, filename, sidecar_file, complex_tca,):
    # --------------------------------
    # debug_print_out('create_tca_correction function', '')
    # --------------------------------
    # Convert RAW
    input_file = os.path.join(path, filename)

    # Read EXIF data
    exif_data = image_read_exif(input_file)

    # Convert RAW file to ppm
    output_file = os.path.join(path, "exported", ("%s.ppm" % os.path.splitext(filename)[0]))

    print("Processing %s ... " % (input_file), flush=True)
    output_file = convert_raw_for_tca(input_file, sidecar_file, output_file)

    tca_correct(output_file, input_file, exif_data, complex_tca,)

    return True

def run_tca(complex_tca):
    # --------------------------------
    # debug_print_out('run_tca function', '')
    # --------------------------------


# ----------------------------------------------------------------------
# added from https://stackoverflow.com/a/13936916 Test if executable exists in Python?
# requires python 3

    # import shutil # not needed here already included

    exec_path = shutil.which("tca_correct") 

    if exec_path is None:
        print(f"no executable found for command 'tca_correct'")
    else:
        print(f"path to executable 'tca_correct': {exec_path}")

# ---------------------------------------------------------------------

    if not os.path.isdir("tca"):
        print("No tca directory, you have to run init first!")
        return

    export_path = os.path.join("tca", "exported")
    if not os.path.isdir(export_path):
        os.mkdir(export_path)

    sidecar_file = os.path.join(export_path, "tca.xmp")
    if not write_sidecar_file(sidecar_file, DARKTABLE_TCA_SIDECAR):
        print("Failed to write sidecar_file: %s" % sidecar_file)
        return

    with concurrent.futures.ProcessPoolExecutor(max_workers=get_max_worker_count()) as executor:
        result_futures = []

        for path, directories, files in os.walk('tca'):
            for filename in files:
                if path != "tca":
                    continue
                if not is_raw_file(filename):
                    continue

                future = executor.submit(create_tca_correction, export_path, path, filename, sidecar_file, complex_tca)

        for f in concurrent.futures.as_completed(result_futures):
            if f.result():
                print("OK")

    if complex_tca:
        merge_final_pdf("tca.pdf", "tca/exported")

def create_vignetting_correction(export_path, path, filename, sidecar_file, distance):
    # --------------------------------
    # debug_print_out('create_vignetting_correction function', '')
    # --------------------------------
    # Convert RAW files to NetPGM
    input_file = os.path.join(path, filename)

    # Read EXIF data
    exif_data = image_read_exif(input_file)

    # Convert the RAW file to ppm
    output_file = os.path.join(export_path, ("%s.ppm" % os.path.splitext(filename)[0]))
    preview_file = os.path.join(export_path, ("%s.jpg" % os.path.splitext(filename)[0]))

    print("Processing %s ... " % (input_file), flush=True)

    output_file = convert_raw_for_vignetting(input_file, sidecar_file, output_file)

    # Create vignetting PGM files (grayscale)
    pgm_file = convert_ppm_for_vignetting(output_file)

    # Calculate vignetting data
    calculate_vignetting(pgm_file, input_file, exif_data, distance)

    # Create preview jpg
    convert_raw_for_vignetting(input_file, sidecar_file, preview_file)

    return True

def run_vignetting():
    # --------------------------------
    # debug_print_out('run_vignetting function', '')
    # --------------------------------
    if not os.path.isdir("vignetting"):
        print("No vingetting directory, you have to run init first!")
        return

    export_path = os.path.join("vignetting", "exported")
    if not os.path.isdir(export_path):
        os.mkdir(export_path)

    sidecar_file = os.path.join(export_path, "vignetting.xmp")
    if not write_sidecar_file(sidecar_file, DARKTABLE_DISTORTION_SIDECAR):
        print("Failed to write sidecar_file: %s" % sidecar_file)
        return

    with concurrent.futures.ProcessPoolExecutor(max_workers=get_max_worker_count()) as executor:
        result_futures = []

        for path, directories, files in os.walk('vignetting'):
            for filename in files:
                distance = float("inf")

                if not is_raw_file(filename):
                    continue

                # Ignore the export path
                if path == export_path:
                    continue

                if path != "vignetting":
                    d = os.path.basename(path)
                    try:
                        distance = float(d)
                    except:
                        continue

                future = executor.submit(create_vignetting_correction, export_path, path, filename, sidecar_file, distance)
                result_futures.append(future)

        for f in concurrent.futures.as_completed(result_futures):
            if f.result():
                print("OK")

    # Create final PDF
    merge_final_pdf("vignetting.pdf", "vignetting/exported")

def run_generate_xml():
    # --------------------------------
    # debug_print_out('run_generate_xml function', '')
    # --------------------------------
    print("Generating lensfun.xml")

    lenses_config_exists = os.path.isfile('lenses.conf')

    if not lenses_config_exists:
        print("lenses.conf doesn't exist, run distortion first")
        return

    # We need maker, model, mount, crop_factor etc.
    lenses = parse_lenses_config('lenses.conf')
    
    # -------------------------------------
    # debug_print_out('', [f'{lenses=}', type(lenses)])
    # a dictionary for the lens of dictionaries corrections dictionaries and the descriptions for the lens
    # lenses is  <class 'dict'>
    # {'Olympus Zuiko Digital 70-300mm F4.0-5.6':{
    #    'distortion':{
    #       '70.0': '0.0, 0.0, 0.0',
    #       '100.0': '0.0, 0.0, 0.0'},
    #    'tca': {},
    #    'vignetting': {},
    #    'maker': 'Olympus Zuiko Digital',
    #    'mount': '4/3 System',
    #    'cropfactor': '2.0',
    #    'aspect_ratio': '4:3',
    #    'type': 'normal'}}
    # ---------------------------------------

    # Scan tca files and add to lenses
    for path, directories, files in os.walk('tca/exported'):
        for filename in files:
            if os.path.splitext(filename)[1] != '.tca':
                continue

            config = configparser.ConfigParser()
            config.read(os.path.join(path, filename))

            for lens_model in config.sections():
                focal_length = config[lens_model]['focal_length']
                if not focal_length in lenses[lens_model]['tca']:
                    lenses[lens_model]['tca'][focal_length] = {}

                for key in config[lens_model]:
                    if key != 'focal_length':
                        lenses[lens_model]['tca'][focal_length][key] = config[lens_model][key]

    # Scan vig files and add to lenses
    for path, directories, files in os.walk('vignetting/exported'):
        for filename in files:
            if os.path.splitext(filename)[1] != '.vig':
                continue

            config = configparser.ConfigParser()
            config.read(os.path.join(path, filename))

            for lens_model in config.sections():
                focal_length = config[lens_model]['focal_length']
                if not focal_length in lenses[lens_model]['vignetting']:
                    lenses[lens_model]['vignetting'][focal_length] = {}

                aperture = config[lens_model]['aperture']
                if not aperture in lenses[lens_model]['vignetting'][focal_length]:
                    lenses[lens_model]['vignetting'][focal_length][aperture] = {}

                distance = config[lens_model]['distance']
                if not distance in lenses[lens_model]['vignetting'][focal_length][aperture]:
                    lenses[lens_model]['vignetting'][focal_length][aperture][distance] = {}

                for key in config[lens_model]:
                    if key != 'focal_length' and key != 'aperture' and key != 'distance':
                        lenses[lens_model]['vignetting'][focal_length][aperture][distance][key] = config[lens_model][key]

    # write lenses to xml
    
    # --------------------------------------------------------------------------------------
    # I have changed the following
    # to put lens model and date in filename for easy integration into ~/.local/share/lensfun/
    # 'with' statement is used to open file for writing ('w' = truncating the file first) for the block then close it
    # open with 'x' option create a new file and open it for writing implies 'w' and raises 'FileExistsError' if the file exists
    # from https://stackoverflow.comn/questions/415511/how-do-i-get-the-current-time-in-python
    # and https://stackoverflow.comn/questions/3545331/how-can-i-getdictionary-key-as-variable-directly-in-python-not-by-searching-fr
    # and https://stackoverflow.comn/questions/12723751/replacing-instances-of-a-character-in-a-string
    
    from time import strftime
    current_time = strftime('_%d-%m-%Y_%H:%M:%S')
    # debug_print_out('date and time are', [f'{current_time=}', type(current_time)])    # <class 'str'>
    first_key = list(lenses.keys())[0]
    # the first item in the list of keys in the dict lenses
    # replace spaces with underscores
    first_key = first_key.replace(' ', '_')
    # debug_print_out('', [f'{first_key=}', type(first_key)])    # <class 'str'>
    filename = first_key + current_time + '.xml'
    # debug_print_out('', [f'{filename=}', type(filename)])    # <class 'str'>
    # with open('mylensfun.xml', 'w') as f:
    with open(filename, 'w') as f:
        # debug_print_out('', [f'{f=}', type(f)])   # <class '_io.TextIOWrapper'>
        # debug_print_out('', [f'{f.name=}', type(f.name)])    # <class 'str'>
    # ------------------------------------------------------------------------------------------
    
        f.write('<lensdatabase>\n')
        for lens_model in lenses:
            f.write('    <lens>\n')
            f.write('        <maker>%s</maker>\n' % lenses[lens_model]['maker'])
            f.write('        <model>%s</model>\n' % lens_model)
            f.write('        <mount>%s</mount>\n' % lenses[lens_model]['mount'])
            f.write('        <cropfactor>%s</cropfactor>\n' % lenses[lens_model]['cropfactor'])
            if lenses[lens_model]['type'] != 'normal':
                f.write('        <type>%s</type>\n' % lenses[lens_model]['type'])

            # Add calibration data
            f.write('        <calibration>\n')

            # Add distortion entries
            #---------------------------------------
            # added for information
            print("adding distortion to xml file")
            # --------------------------------------
            
            focal_lengths = lenses[lens_model]['distortion'].keys()
            for focal_length in sorted(focal_lengths, key=float):
                data = list(map(str.strip, lenses[lens_model]['distortion'][focal_length].split(',')))
                if data[1] is None:
                    f.write('            '
                            '<distortion model="poly3" focal="%s" k1="%s" />\n' %
                            (focal_length, data[0]))
                else:
                    f.write('            '
                            '<distortion model="ptlens" focal="%s" a="%s" b="%s" c="%s" />\n' %
                            (focal_length, data[0], data[1], data[2]))

            # Add tca entries

            #---------------------------------------
            # added for information
            print("adding tca to xml file")
            # --------------------------------------

            focal_lengths = lenses[lens_model]['tca'].keys()
            for focal_length in sorted(focal_lengths, key=float):
                data = lenses[lens_model]['tca'][focal_length]
                if data['complex_tca'] == 'True':
                    f.write('            '
                            '<tca model="poly3" focal="%s" br="%s" vr="%s" bb="%s" vb="%s" />\n' %
                            (focal_length, data['br'], data['vr'], data['bb'], data['vb']))
                else:
                    f.write('            '
                            '<tca model="poly3" focal="%s" vr="%s" vb="%s" />\n' %
                            (focal_length, data['vr'], data['vb']))

            # Add vignetting entries

            #---------------------------------------
            # added for information            
            print("adding vignetting to xml file")
            # --------------------------------------
            
            focal_lengths = lenses[lens_model]['vignetting'].keys()
            for focal_length in sorted(focal_lengths, key=float):
                apertures = lenses[lens_model]['vignetting'][focal_length].keys()
                for aperture in sorted(apertures, key=float):
                    distances = lenses[lens_model]['vignetting'][focal_length][aperture].keys()
                    for distance in sorted(distances, key=float):
                        data = lenses[lens_model]['vignetting'][focal_length][aperture][distance]

                        if distance == 'inf':
                            distance = '1000'

                        _distances = [ distance ]

                        # If we only have an infinite distance, we need to write two values
                        if len(distances) == 1 and distance == '1000':
                            _distances = [ '10', '1000' ]

                        for _distance in _distances:
                            f.write('            '
                                    '<vignetting model="pa" focal="%s" aperture="%s" distance="%s" '
                                    'k1="%s" k2="%s" k3="%s" />\n' %
                                    (focal_length, aperture, _distance,
                                     data['k1'], data['k2'], data['k3']))

            f.write('        </calibration>\n')
            f.write('    </lens>\n')
        f.write('</lensdatabase>\n')

def run_ship():
    # --------------------------------
    # debug_print_out('run_ship function', '')
    # --------------------------------
    if not os.path.exists("lensfun.xml"):
        print("lensfun.xml not found, please run the calibration steps first!")
        return

    tar_files = [ "lensfun.xml", "tca.pdf", "vignetting.pdf" ]
    tar_name = "lensfun_calibration.tar.xz"

    vignetting_dir = 'vignetting/exported'
    if os.path.exists(vignetting_dir):
        for path, directories, files in os.walk(vignetting_dir):
            for filename in files:
                if os.path.splitext(filename)[1] != '.jpg':
                    continue

                tar_files.append(os.path.join(vignetting_dir, filename))

    tar = tarfile.open(tar_name, 'w:xz')

    for f in tar_files:
        if not os.path.exists(f):
            continue

        try:
            tinfo = tar.gettarinfo(name=f)

            tinfo.uid = 0
            tinfo.gid = 0
            tinfo.uname = "root"
            tinfo.gname = "root"
        except OSError:
            continue

        fh = open(f, "rb")
        tar.addfile(tinfo, fileobj=fh)
        fh.close()

    tar.close()

    print("Created lensfun_calibration.tar.xz")
    print("Open a bug at https://github.com/lensfun/lensfun/issues/ with the data.")

class CustomDescriptionFormatter(argparse.ArgumentDefaultsHelpFormatter, argparse.RawDescriptionHelpFormatter):
    pass

def main():
    # --------------------------------
    # debug_print_out('main function', '')
    # import os module to change the working directory and enable running in idle
    # os.chdir('./50mm + filter')
    # print(os.getcwd()) # view the current working directory
    # debug_print_out('the current working dir is: ', os.getcwd())
    # --------------------------------


    description = '''
This is an overview about the calibration steps.\n
\n
To setup the required directory structure simply run:

    lens_calibrate.py init

The next step is to copy the RAW files you created to the corresponding
directories.

Once you have done that run:

    lens_calibrate.py distortion

This will create tiff file you can use to figure out the the lens distortion
values (a), (b) and (c) using hugin. It will also create a lenses.conf where
you need to fill out missing values.

If you don't want to do distortion corrections you need to create the
lenses.conf file manually. It needs to look like this:

    [MODEL NAME]
    maker =
    mount =
    cropfactor =
    aspect_ratio =
    type =

The section name needs to be the lens model name you can figure out with:

    exiv2 -g LensModel -pt <raw file>

The required options are:

maker:        is the manufacturer or the lens, e.g. 'FE 16-35mm F2.8 GM'
mount:        is the name of the mount system, e.g. 'Sony E'
cropfactor:   is the crop factor of the camera as a float, e.g. '1.0' for full
              frame
aspect_ratio: is the aspect ratio of your camera, normally it is '3:2'
type:         is the type of the lens, e.g. 'normal' for rectilinear lenses.
              Other possible values are: stereographic, equisolid, stereographic,
              panoramic or fisheye.

If you want TCA corrections just run:

    lens_calibrate.py tca

If you want vignetting corrections run:

    lens_calibrate.py vignetting

Once you have created data for all corrections you can generate an xml file
which can be consumed by lensfun. Just call:

    lens_calibrate.py generate_xml

To use the data in your favourite software you just have to copy the generated
lensfun.xml file to:

    ~/.local/share/lensfun/

If you want to submit the data to the lensfun project run:

    lens_calibrate.py ship

then create a bug report to add the lens calibration data to the project at:

  https://github.com/lensfun/lensfun/issues/

and provide the lensfun_calibratrion.tar.xz

-----------------------------

'''

    parser = argparse.ArgumentParser(description=description,
                                     formatter_class=CustomDescriptionFormatter)

    parser.add_argument('--complex-tca',
                        action='store_true',
                        help='Turns on non-linear polynomials for TCA')
    #parser.add_argument('-r, --rawconverter', choices=['darktable', 'dcraw'])

    parser.add_argument('action',
                        choices=[
                            'init',
                            'distortion',
                            'tca',
                            'vignetting',
                            'generate_xml',
                            'ship'],
                        help='This runs one of the actions for lens calibration')

    args = parser.parse_args()

    if args.action == 'init':
        init()
    elif args.action == 'distortion':
        run_distortion()
    elif args.action == 'tca':
        run_tca(args.complex_tca)
    elif args.action == 'vignetting':
        run_vignetting()
    elif args.action == 'generate_xml':
        run_generate_xml()
    elif args.action == 'ship':
        run_ship()

if __name__ == "__main__":
    main()
