"""Consistent local data backup. Browser/Claude credentials are excluded."""
import datetime
import json
import sqlite3
import tempfile
import zipfile
from pathlib import Path
from .instance import single_instance


def backup(config,destination=None):
    folder=Path(destination) if destination else config.data.parent/'ClaraBackups'
    folder.mkdir(parents=True,exist_ok=True)
    if folder.resolve().is_relative_to(config.data.resolve()):
        raise ValueError('Choose a backup folder outside Clara data.')
    name='clara-'+datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%d-%H%M%S-%f')+'.zip'
    target=folder/name
    with single_instance(config.data), tempfile.TemporaryDirectory() as temp:
        source=config.data/'clara.sqlite3';snapshot=Path(temp)/'clara.sqlite3'
        if source.exists():
            with sqlite3.connect(source) as src,sqlite3.connect(snapshot) as dst: src.backup(dst)
        with zipfile.ZipFile(target,'x',zipfile.ZIP_DEFLATED) as archive:
            if snapshot.exists(): archive.write(snapshot,'clara.sqlite3')
            for relative in ['settings.json','cpa-skill-manifest.json','workspace','artifacts','attachments','evidence']:
                p=config.data/relative
                files=[p] if p.is_file() else sorted(p.rglob('*')) if p.is_dir() else []
                for file in files:
                    if file.is_file() and not file.is_symlink() and file.resolve().is_relative_to(config.data.resolve()):
                        archive.write(file,str(file.relative_to(config.data)))
            archive.writestr('backup-manifest.json',json.dumps({'format':1,'original_data':str(config.data),
                'note':'Restore into the same data path to preserve absolute file references. Browser and Claude account state excluded.'}))
    return target


def restore(archive_path,destination):
    destination=Path(destination).resolve()
    if destination.exists(): raise ValueError('Restore requires a new, empty destination. Move the old data aside first.')
    with zipfile.ZipFile(archive_path) as archive:
        if sum(i.file_size for i in archive.infolist())>5_000_000_000:
            raise ValueError('Backup exceeds the 5 GB restore bound.')
        for i in archive.infolist():
            p=Path(i.filename)
            if p.is_absolute() or '..' in p.parts or ':' in i.filename or '\\' in i.filename or (i.external_attr>>16)&0o170000==0o120000:
                raise ValueError('Unsafe backup entry.')
        metadata=json.loads(archive.read('backup-manifest.json'))
        if metadata.get('format')!=1 or Path(metadata['original_data']).resolve()!=destination:
            raise ValueError('Restore to the original data path recorded in the backup, after moving the current data aside.')
        destination.mkdir(parents=True)
        archive.extractall(destination)
    return destination
