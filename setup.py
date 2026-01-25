from setuptools import setup, find_packages

# endregion
setup(
    name="esp32-audio-remote",
    version="1.0.0",
    description="CircuitPython-based audio remote with BM83, BLE HID, and Nextion display",
    author="Your Name",
    author_email="you@example.com",
    url="https://github.com/yourusername/esp32-audio-remote",
    packages=find_packages(where="firmware/circuitpython"),
    package_dir={"": "firmware/circuitpython"},
    include_package_data=True,
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
    ],
    python_requires=">=3.7",
)