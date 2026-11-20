# 0414
#noshot
guest shell 'getprop | grep -iE "vsoc|cutf|cuttlefish|virtual|emulat|generic|qemu|goldfish|ranchu|uml|kernarium|test-keys|userdebug" | cut -c1-170; echo ---; getprop ro.product.property_source_order; getprop ro.build.characteristics; getprop | grep -E "^\[ro\.(product|build)\.[a-z_.]*(model|fingerprint|device|name|brand|manufacturer|board|tags|type|flavor|description|display.id|product|host|user)\]" | cut -c1-170'
