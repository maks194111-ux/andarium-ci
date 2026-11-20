# 0002
#noshot
UA="Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 Chrome/126 Mobile Safari/537.36"
( curl -fsSL --retry 3 -A "$UA" -o "$WORK/live-package.zip" 'https://data.winudf.com/XAPK/Y29tLnN1cGVyY2VsbC5icmF3bHN0YXJzXzcwODc3XzY2YjNhY2Fl?_p=Y29tLnN1cGVyY2VsbC5icmF3bHN0YXJz&filename=Brawl+Stars_70.877_APKPure.xapk&full_size=2015333875&is_hot=true&k=364a51fe21b2f5cfdc3f6fe818644c2a6b029a9c&package_name=com.supercell.brawlstars&source=web&token=1795159964-d625494d28-0-c192ea1d42980601d9b2a74df8122466' && mkdir -p "$WORK/live-package" && unzip -oq "$WORK/live-package.zip" -d "$WORK/live-package" && touch "$WORK/live-package.ready" ) > "$WORK/live-package.log" 2>&1 &
sleep 20; ls -la "$WORK/live-package.zip"; cat "$WORK/live-package.log"
