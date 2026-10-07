# SPDX-License-Identifier: AGPL-3.0-or-later
from setuptools import setup


setup(
    name='folio-pdf-reader',
    version='0.2.2',
    description='A focused desktop PDF reader',
    license='AGPL-3.0-or-later',
    license_files=['LICENSE'],
    packages=['folio_reader'],
    package_data={'folio_reader': ['style.qss', 'icon.png']},
    python_requires='>=3.10',
    install_requires=['PyQt5==5.15.11', 'PyMuPDF==1.28.2'],
    entry_points={'console_scripts': ['folio-pdf-reader=folio_reader.app:main']},
)
