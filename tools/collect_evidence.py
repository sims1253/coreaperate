"""Collect local test evidence and dependency license texts, without credentials."""
from pathlib import Path
from importlib import metadata
import hashlib
import json
import platform
import shutil

Path('licenses').mkdir(exist_ok=True)
evidence_dir=Path('runtime/evidence')
evidence_dir.mkdir(parents=True,exist_ok=True)
for name in ['websockets','pytest','lupa','colorama','iniconfig','packaging','pluggy','Pygments','setuptools']:
    try:
        dist=metadata.distribution(name)
    except metadata.PackageNotFoundError:
        continue
    for file in dist.files or []:
        if 'license' in file.name.lower() or 'copying' in file.name.lower():
            target=Path('licenses')/(name+'-'+file.name)
            shutil.copyfile(dist.locate_file(file),target)
            if name=='lupa' and file.name=='LICENSE.txt':
                lines=target.read_text(encoding='utf8').splitlines()
                if len(lines)>1 and set(lines[1])=={'='}: lines[1]=''
                target.write_text('\n'.join(lines).rstrip()+'\n',encoding='utf8',newline='\n')
source=Path('reaper/lib/dkjson.lua').read_text(encoding='utf8')
Path('licenses/dkjson-MIT.txt').write_text(source[source.index('Copyright (C)'):source.index('--]==]')].rstrip()+'\n',encoding='utf8',newline='\n')
versions={n:metadata.version(n) for n in ['websockets','pytest','lupa']}
evidence=dict(platform=platform.platform(),python=platform.python_version(),dependencies=versions,
              dkjson_sha256=hashlib.sha256(Path('reaper/lib/dkjson.lua').read_bytes()).hexdigest())
(evidence_dir/'environment.json').write_text(json.dumps(evidence,indent=2),encoding='utf8')
for src,name in [('reaper/probe-result.txt','reaper-probe-result.txt'),('runtime/smoke-result.txt','reaper-smoke-result.txt')]:
    if Path(src).exists(): shutil.copyfile(src,evidence_dir/name)
