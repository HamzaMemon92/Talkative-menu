@echo off
setlocal

set "WHISPER_SERVER=D:\talkative menu\runtimes\whisper.cpp\Release\whisper-server.exe"
set "WHISPER_MODEL=D:\talkative menu\models\speech-to-text\whisper\ggml-large-v3-turbo-q5_0.bin"

if not exist "%WHISPER_SERVER%" (
  echo Missing whisper-server: %WHISPER_SERVER%
  exit /b 1
)
if not exist "%WHISPER_MODEL%" (
  echo Missing Whisper model: %WHISPER_MODEL%
  exit /b 1
)

"%WHISPER_SERVER%" -m "%WHISPER_MODEL%" --host 127.0.0.1 --port 8082 -t 4 -p 1 -l auto -nt
