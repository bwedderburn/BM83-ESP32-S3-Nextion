#!/bin/bash
echo "Running tests with coverage..."
coverage run -m pytest tests/
coverage report -m
