# Andarium: первый запуск на бесплатном macOS runner

Это отдельный минимальный репозиторий для проверки среды GitHub Actions.
Он собирает неподписанное приложение под iOS 18 без образа Android (эксперимент), не запускает Android и не подтверждает работу на iOS 18 или FPS.
Исходники движка скачиваются из публичного upstream на закреплённом коммите.

## Запуск

1. Создать отдельный публичный репозиторий в GitHub.
2. Поместить `.github/workflows/macos-preflight.yml` из этой папки в тот же
   путь нового репозитория. Остальное содержимое рабочей среды не копировать.
3. В Actions выбрать **Andarium macOS readiness → Run workflow**.
4. Проверить журнал и Summary: Xcode/SDK, доступность Metal, компиляцию
   Swift-моделей и результат тестов либо явное сообщение, почему они не запущены.

Запуск ручной, только на стандартном runner `xcode-27`, только в публичном
репозитории, с ограничением 30 минут. Нет платных larger runners, загрузки
артефактов, кешей, секретов, подписи Apple или автоматической публикации.
Доступность runner и достаточность ресурсов проверяются первым запуском.
Не заменять его на платный runner при ошибке.

Успех этой проверки означает лишь готовность части инструментов. Для полной
сборки далее нужны зависимости и принятые upstream-артефакты ядра, описанные
в документации Kernarium. Если графика недоступна, нельзя называть эту
машину средой проверки графики Android.

## Проверки переноса на iOS 18

- `iOS 18 compatibility compilation` применяет слой совместимости к
  закреплённым исходникам и компилирует настоящий интерфейс приложения с
  минимальной версией iOS 18. Современный интерфейс сохраняется на новых
  версиях iOS; на старых используются системные материалы, кнопки и API
  ориентации. Схема Preview не содержит эмулятор, поэтому её успешная сборка
  не подтверждает запуск Android.
- `iOS 18 candidate graphics driver probe` проверяет отдельный кандидат
  графического драйвера MoltenVK: создание устройства, отправку команды
  заполнения буфера и чтение результата. Это проверка на macOS, а не на
  iPhone. Драйвер не встроен в Andarium; список доступных расширений нужен
  для последующего сопоставления с требованиями рендерера.

Дополнительные проверки:

- `iOS 18 device driver link` компонует тест Vulkan для настоящего устройства
  arm64 с минимальной iOS 18 и проверяет команды загрузки Mach-O у программы
  и MoltenVK. Это не запуск на телефоне и не готовая IPA.
- `iOS 18 graphics bridge build` собирает именно исправленную Mesa/Zink из
  исходников Andarium с MoltenVK, затем проверяет контекст OpenGL 4.6 и чтение
  пикселя framebuffer. Исходники проходят штатную проверку происхождения.
  Проверка не включает Virgl/Venus, гостевой Android, Google или измерение FPS.
  Она намеренно не снижает запрашиваемую версию OpenGL и не включает
  программный рендерер. Отказ теста 4.6 сам по себе не доказывает невозможность
  работы ограниченного контекста; такой контекст не является целью проверки.
  Сборка выполняется на macOS и ограничена 45 минутами.

Все проверки ручные, без загрузки артефактов и без платных runner. Защита
от запуска штатного графического движка без Metal 4 не отключается. Изменение
версии в настройках проекта само по себе не делает готовую IPA совместимой
с iOS 18.

## Подтверждённая несовместимость графического адаптера

Сборка Mesa/Zink с MoltenVK 1.4.2 проходит. Исполнение останавливается **раньше
создания контекста OpenGL**:

```
MESA: error: Zink requires the nullDescriptor feature of KHR/EXT robustness2.
FAIL: initialize Zink EGL (EGL error 0x3001)
```

Это не отказ компилятора и не доказательство того, что OpenGL 4.6 проверен.
В исходниках MoltenVK 1.4.2 `nullDescriptor` объявлен неподдерживаемым независимо
от модели GPU. Соответствующая возможность обсуждается в
[upstream issue](https://github.com/KhronosGroup/MoltenVK/issues/2650).
Наличие расширения `robustness2` не означает поддержку каждого его feature bit.

Нельзя исправлять это включением флага без реализации, удалением проверки Zink
или подменой результата теста. Нужна корректная обработка нулевых ресурсов:
чтения возвращают нули, записи и атомарные операции отбрасываются. Затем нужно
заново проверять создание контекста, шейдеры и рендеринг. Отдельно сохраняется
задача переноса собственных callback-функций учёта памяти KosmicKrisp,
используемых Virgl/Venus. Текущая конфигурация не предназначена для упаковки IPA.

## Zink on MoltenVK: result

`ios18/zink_null_descriptor_fallback.py` gives Zink real placeholder resources where MoltenVK lacks `nullDescriptor`. With it, the patched Mesa builds and EGL initialises, but the driver offers at most desktop OpenGL 2.1 (the probe requires 4.6 and fails on purpose). MoltenVK has no transform feedback or geometry shaders, which Mesa needs for OpenGL 3.0 and later. This route cannot serve the Android guest.

## ANGLE on Metal: result

ANGLE's Metal backend needs neither Metal 4 nor Vulkan. `ios18-angle-build.yml` builds it from pinned sources: the macOS build renders and reads back a frame, and the same sources link for the arm64 iOS device with minimum iOS 18.0. It offers OpenGL ES 3.0 (with transform feedback), not 3.1/3.2, has no `GL_EXT_buffer_storage`, and gives the guest no Vulkan. It has not run on a phone.

## Virgl on ANGLE: result

`ios18-virgl-angle.yml` builds Andarium's patched virglrenderer and libepoxy against that ANGLE build (Venus off) and drives it the way the engine does: external EGL display, contexts through callbacks. On macOS the renderer initialises, creates a guest context, and a Virgl command stream clears a render target that reads back correctly. The capability set it would hand the guest is GLSL level 130, i.e. about OpenGL 3.0 / OpenGL ES 3.0, with 8 render targets and 16384 textures. This is a host-side test only: the engine's own GPU device code is not yet built against ANGLE, no Android guest has booted on it, and the guest has no Vulkan on this path.

## Andarium's renderer on ANGLE: result

`ios18/angle_provider.py` retargets the engine's own host GL provider (`darwin/device/gpu/host_gl_provider.cpp`) from Mesa to ANGLE's Metal backend, and the engine is compiled in upstream's Virgl-only mode (the one its iOS Simulator product uses: no guest Vulkan, scanouts read back). In `ios18-virgl-angle.yml` the engine's `VirglRenderer` class then creates a guest GL context on macOS, executes a command stream and returns the scanout pixels through the display's readback call. The same engine sources compile for arm64 iOS 18.0 (compile only). Not done: the full engine and app build, booting Android on this path, zero-copy presentation, anything on a phone.

## iOS 18 engine and app build (experiment)

`ios18-engine-build.yml` builds the whole device runtime for arm64 iOS 18.0 on the ANGLE path (libepoxy, virglrenderer, network stack, the upstream release kernel bundle, `KernariumRuntime`) and packages it with ANGLE's frameworks. `ios18-app-build.yml` builds the Andarium app against that package with minimum iOS 18.0 and ad-hoc signs it with upstream's entitlements. The artifact carries no Android system image. Both workflows succeed; the result has never run on a device, so Android boot, graphics (OpenGL ES 3.0, no Vulkan, readback presentation), frame rate and stability are unverified.

## Frame measurements and small memory limits (ANGLE path, macOS host)
The boot test runs three profiles (120 Hz without a memory limit; 60 Hz at 828x1792 with a 2098 MiB process limit and 1408 or 1024 MiB of guest RAM) and records display statistics, application frame times, guest memory and the host's frame copy cost. On the hosted 3-core Mac: scrolling Settings takes about 12 ms per frame at the median (18-25 ms at the 90th percentile), the notification shade about 27-36 ms; the frame copy costs about 1 ms. The limit is the guest's UI thread, not the display path. These are not phone figures.
ios18/lowmem_patch.py gives a new guest the RAM that fits on devices whose limit leaves less than 1536 MiB (floor 1024 MiB) and lets the settings offer sizes from 1024 MiB.
