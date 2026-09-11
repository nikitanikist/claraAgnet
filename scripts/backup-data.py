import argparse
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from clara.config import Config,default_data
from clara.backup import backup,restore

parser=argparse.ArgumentParser(description='Stop Clara before backup or restore. Backups stay local.')
parser.add_argument('--data-dir',type=Path,default=default_data())
parser.add_argument('--restore',type=Path)
args=parser.parse_args()
if args.restore:
    print(restore(args.restore,args.data_dir))
else:
    cfg=Config(args.data_dir)
    if not cfg.data.is_dir(): raise SystemExit('Clara data folder does not exist.')
    print(backup(cfg))
