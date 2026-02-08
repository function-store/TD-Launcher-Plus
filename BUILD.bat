
@echo off
setlocal

set PYTHON_EXECUTABLE=.\venv\Scripts\python.exe

echo Cleaning previous build...
if exist "dist\td_launcher_plus" rmdir /s /q "dist\td_launcher_plus"
if exist "build\td_launcher_plus" rmdir /s /q "build\td_launcher_plus"

echo Installing dependencies...
%PYTHON_EXECUTABLE% -m pip install -r requirements.txt

%PYTHON_EXECUTABLE% -m PyInstaller --noconfirm --log-level=WARN ^
--onedir ^
--windowed ^
--name="td_launcher_plus" ^
--icon="td_launcher_plus.ico" ^
--add-data="td_launcher_plus.ico;." ^
--add-data="touchdesigner.png;." ^
--hidden-import="PIL" ^
--hidden-import="PIL.Image" ^
--hidden-import="PIL.ImageOps" ^
--add-binary="toeexpand/toeexpand.exe;toeexpand" ^
--add-binary="test.toe;." ^
--add-binary="toeexpand/iconv.dll;toeexpand" ^
--add-binary="toeexpand/icudt59.dll;toeexpand" ^
--add-binary="toeexpand/icuuc59.dll;toeexpand" ^
--add-binary="toeexpand/libcurl.dll;toeexpand" ^
--add-binary="toeexpand/libcurl-x64.dll;toeexpand" ^
--add-binary="toeexpand/zlib1.dll;toeexpand" ^
.\td_launcher.py

echo Finished build!

endlocal