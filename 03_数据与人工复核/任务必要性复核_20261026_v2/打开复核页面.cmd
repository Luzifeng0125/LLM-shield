@echo off
if not exist "%~dp0action_review.html" (
  echo Missing action_review.html. Extract the complete review folder first.
  pause
  exit /b 1
)
start "" "%~dp0action_review.html"
