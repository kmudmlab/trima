#!/bin/bash
# log time, Tctl, mean core MHz every 2 s until killed
while true; do
  t=$(sensors 2>/dev/null | awk "/Tctl/{gsub(/[+°C]/,\"\",\$2); print \$2}")
  f=$(awk "/MHz/{s+=\$4;n++} END{printf \"%.0f\", s/n}" /proc/cpuinfo)
  echo "$(date +%T) $t $f"
  sleep 2
done
