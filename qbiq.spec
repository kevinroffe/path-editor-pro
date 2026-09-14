# qbiq.spec — PyInstaller build spec for qbiq Path Editor
from PyInstaller.utils.hooks import collect_all, collect_data_files

block_cipher = None

# Collect ifcopenshell native binaries and data
ifc_datas, ifc_binaries, ifc_hidden = collect_all('ifcopenshell')

# Collect ezdxf data files (font/template resources)
ezdxf_datas = collect_data_files('ezdxf')

a = Analysis(
    ['main.py'],
    pathex=['backend'],
    binaries=ifc_binaries,
    datas=[
        ('frontend', 'frontend'),
        ('backend',  'backend'),
    ] + ifc_datas + ezdxf_datas,
    hiddenimports=[
        'flask_cors',
        'werkzeug',
        'werkzeug.serving',
        'werkzeug.utils',
        'scipy.spatial',
        'scipy.spatial.qhull',
        'scipy.interpolate',
        'scipy._lib.messagestream',
        'numpy',
        'ezdxf',
        'ezdxf.layouts',
        'ezdxf.entities',
        'ezdxf.document',
        'ifcopenshell',
        'ifcopenshell.geom',
        'ifcopenshell.util',
        'ifcopenshell.util.element',
        'svgwrite',
        'tkinter',
        'tkinter.ttk',
    ] + ifc_hidden,
    hookspath=[],
    runtime_hooks=[],
    excludes=['matplotlib', 'PyQt5', 'PyQt6', 'PySide2', 'PySide6',
              'IPython', 'jupyter', 'pytest'],
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
    name='qbiq-path-editor',
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
    name='qbiq-path-editor',
)
