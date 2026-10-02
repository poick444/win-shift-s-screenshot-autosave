# Kadr — Win + Shift + S screenshot autosave for Windows

Kadr automatically saves screenshots you take with **Win + Shift + S**. Select an area in the Windows capture overlay, and Kadr saves the image to a folder you choose. It runs in the system tray, so you can close the window and keep saving screenshots.

[Download Kadr 1.1 for Windows](download/Kadr-1.1.exe) · [Инструкция на русском](README.ru.md)

## Features

- Automatically save area screenshots taken with Win + Shift + S
- Choose the save folder and PNG or JPG format
- Start with Windows if you enable the option
- Keep running in the tray after closing the window
- Preview the latest screenshot and open its folder
- Save screenshots locally; Kadr does not upload them

## Use

1. Download and run `Kadr-1.1.exe`.
2. Choose a folder and image format in Kadr.
3. Press **Win + Shift + S**, select an area, and wait for the screenshot to appear in the app.

The default folder is `Pictures\Screenshots`. Double-click the tray icon to reopen Kadr. To stop it, right-click the icon and choose **Quit**. If you move the executable, enable **Start with Windows** again so Windows uses its new location.

Kadr needs the Windows screenshot overlay to work. If Win + Shift + S does not open it, Kadr cannot capture the screen by itself.

## Run from source

Requires Windows and Python 3.10 or newer:

```powershell
py -m pip install -r requirements.txt
py main.py
```

To build a single executable, run `build.bat`. To run the tests, use `py -m unittest discover -s tests`.

## How it works

Kadr listens for Win + Shift + S and waits for a new clipboard image. It prefers PNG and DIB data, including when Windows also exposes the capture as a file. Clipboard images from other actions are ignored.

Settings are stored in `%LOCALAPPDATA%\Kadr\settings.json`. A small rotating diagnostic log is stored in `%LOCALAPPDATA%\Kadr\kadr.log`; it contains event times, errors, image dimensions, and saved paths, but no image contents.

Licensed under [MIT](LICENSE).
