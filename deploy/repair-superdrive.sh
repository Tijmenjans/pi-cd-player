#!/bin/bash
# Targeted repair for Apple USB SuperDrive 05ac:1500. Run with sudo on the Pi.
set -euo pipefail
if [ "$(id -u)" -ne 0 ]; then echo 'Start dit script met sudo.'; exit 1; fi
repair_backup="/home/tijmen/cdspeler/backups/superdrive-system-$(date +%Y%m%d-%H%M%S)"
mkdir -p "$repair_backup"
for repair_file in /etc/udev/rules.d/60-cdrom_id.rules /etc/udev/rules.d/90-apple-superdrive.rules /etc/systemd/system/cdspeler-superdrive-wake@.service; do
 if [ -f "$repair_file" ]; then cp -a "$repair_file" "$repair_backup/"; fi
done
cp /usr/lib/udev/rules.d/60-cdrom_id.rules "$repair_backup/vendor-60-cdrom_id.rules"
cdspeler_user_service() { runuser -u tijmen -- env XDG_RUNTIME_DIR=/run/user/1000 systemctl --user "$@"; }
trap 'cdspeler_user_service start cdspeler-web || true' EXIT
cdspeler_user_service stop cdspeler-web
python3 - <<'PY'
from pathlib import Path
source=Path('/usr/lib/udev/rules.d/60-cdrom_id.rules').read_text()
needle='IMPORT{program}="cdrom_id --lock-media $devnode"'
if source.count(needle)!=1:raise SystemExit('Onverwachte udev-regel: niets aangepast')
# Retain all distribution rules for other drives. This SuperDrive is polled
# only by the player, avoiding simultaneous TOC/lock requests during ripping.
rule='ATTRS{idVendor}=="05ac", ATTRS{idProduct}=="1500", ENV{ID_CDROM}="1", ENV{UDISKS_IGNORE}="1", GROUP="cdrom", MODE="0660", SYMLINK+="cdspeler-drive", GOTO="cdrom_end"'
Path('/etc/udev/rules.d/60-cdrom_id.rules').write_text(source.replace(needle,rule+'\n\n'+needle))
Path('/etc/udev/rules.d/90-apple-superdrive.rules').write_text('ACTION=="add", SUBSYSTEM=="block", KERNEL=="sr[0-9]*", ATTRS{idVendor}=="05ac", ATTRS{idProduct}=="1500", TAG+="systemd", ENV{SYSTEMD_WANTS}+="cdspeler-superdrive-wake@%k.service"\n')
Path('/etc/systemd/system/cdspeler-superdrive-wake@.service').write_text('''[Unit]
Description=Initialize Apple SuperDrive %I
BindsTo=dev-%i.device
After=dev-%i.device
[Service]
Type=oneshot
ExecStart=/usr/bin/sg_raw --timeout=5 /dev/%I EA 00 00 00 00 00 01
TimeoutStartSec=10
TimeoutStopSec=2
RemainAfterExit=yes
''')
PY
systemctl daemon-reload
# Recover a daemon whose control socket stopped replying during the USB reset storm.
if ! timeout 20s systemctl restart systemd-udevd.service; then
 echo 'Apparaatdienst reageert nog niet direct; directe drive-rechten worden wel hersteld.'
fi
# Pending pre-repair udev probes are stopped once, without killing unrelated jobs.
python3 - <<'PY'
import os,re,signal,grp
from pathlib import Path
for p in Path('/proc').iterdir():
 if not p.name.isdigit():continue
 try:
  args=(p/'cmdline').read_bytes().split(b'\0')
  if args and Path(os.fsdecode(args[0])).name=='cdrom_id' and b'--lock-media' in args and any(re.fullmatch(rb'/dev/sr[0-9]+',a) for a in args):os.kill(int(p.name),signal.SIGTERM)
 except (OSError,ValueError):pass
for node in Path('/sys/class/block').glob('sr[0-9]*'):
 if not any((p/'idVendor').exists() and (p/'idProduct').exists() and (p/'idVendor').read_text().strip()=='05ac' and (p/'idProduct').read_text().strip()=='1500' for p in node.resolve().parents):continue
 device=Path('/dev')/node.name
 if device.exists():
  os.chown(device,-1,grp.getgrnam('cdrom').gr_gid);os.chmod(device,0o660)
  Path('/dev/cdspeler-drive').unlink(missing_ok=True);Path('/dev/cdspeler-drive').symlink_to(device)
  print('Toegang hersteld:',device,flush=True)
PY
timeout 8s udevadm control --reload-rules || true
timeout 8s udevadm trigger --action=change --subsystem-match=block --sysname-match='sr*' || true
for repair_node in /sys/class/block/sr*; do
 [ -e "$repair_node" ] || continue
 repair_name="$(basename "$repair_node")"
 if [ "$(readlink -f /dev/cdspeler-drive 2>/dev/null)" = "/dev/$repair_name" ]; then
  if ! timeout 15s systemctl start "cdspeler-superdrive-wake@$repair_name.service"; then
   echo 'Initialiseren lukte niet direct. Sluit alleen de SuperDrive opnieuw aan.'
  fi
 fi
done
cdspeler_user_service start cdspeler-web
echo 'SuperDrive-regels en toegang hersteld. De webapp is gestart.'
echo "Back-up: $repair_backup"
