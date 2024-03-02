lens_calibrate.py
=================

This repository is a version of <a href="https://gitlab.com/cryptomilk">Andreas Schneider's</a> original repository cloned and imported here from <a href="https://gitlab.com/cryptomilk/lens_calibrate">Gitlab</a>

He is here on Github as <a href="https://github.com/cryptomilk">"Cryptomilk"</a>

I ran in to trouble using the script to calibrate my four-thirds mount Olympus DSLR lens collection which have patchy support on lensfun and as they are now discontinued and can only be used with an an adapter on micro 4/3 the chances of them being supported are minimal. 
As a total novice in coding with no experience of python this code probably contains a bag full of errors, but I have modified the script to extract more metadata using <a href="https://exiftool.org/">ExifTool by Phil Harvey</a> and better suit my work flow.

I have also changed two deprecation errors:
1. "PyPDF2.errors.DeprecationError: PdfFileMerger is deprecated and was removed in PyPDF2 3.0.0. Use PdfMerger instead" from PyPDF2 import PdfFileMerger
2. "lens_calibrate.py:50: DeprecationWarning: Please use `leastsq` from the `scipy.optimize` namespace the `scipy.optimize.minpack` namespace is deprecated from scipy.optimize.minpack import leastsq

  but I have no ides what the implications of this are and I've changed nothing else relating to this, however the code appears to work correctly.
