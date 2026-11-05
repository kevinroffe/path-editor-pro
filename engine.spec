# engine.spec — PyInstaller build of the headless engine the Revit add-in starts (qbiq-engine.exe).
# Derived from qbiq.spec (the desktop exe): same data and hidden imports, no tkinter window.
from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_submodules

block_cipher = None

ifc_datas, ifc_binaries, ifc_hidden = collect_all('ifcopenshell')
ezdxf_datas = collect_data_files('ezdxf')
# Imported as `from shapely import wkt` etc.: PyInstaller's analysis does not always see these submodules.
shapely_hidden = collect_submodules('shapely')
networkx_hidden = collect_submodules('networkx')

a = Analysis(
    ['engine_main.py'],
    pathex=['backend'],
    binaries=ifc_binaries,
    datas=[
        ('frontend', 'frontend'),
        ('backend',  'backend'),
        ('run.py',    '.'),
    ] + ifc_datas + ezdxf_datas,
    hiddenimports=[
        'run',
        'flask_cors',
        'werkzeug',
        'werkzeug.serving',
        'werkzeug.utils',
        'scipy.spatial',
        'scipy.spatial.qhull',
        'scipy.interpolate',
        'scipy._lib.messagestream',
        'numpy',
        'shapely',
        'networkx',
        'ezdxf',
        'ezdxf.layouts',
        'ezdxf.entities',
        'ezdxf.document',
        'ifcopenshell',
        'ifcopenshell.geom',
        'ifcopenshell.util',
        'ifcopenshell.util.element',
        'svgwrite',
    ] + ifc_hidden + shapely_hidden + networkx_hidden,
    hookspath=[],
    runtime_hooks=[],
    excludes=['matplotlib', 'PyQt5', 'PyQt6', 'PySide2', 'PySide6', 'IPython', 'jupyter', 'pytest', 'tkinter'],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='qbiq-engine',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    icon=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    name='qbiq-engine',
)
