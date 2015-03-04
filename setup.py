from setuptools import setup

setup(
    name='hipochat',
    version='0.1',
    long_description=__doc__,
    packages=['hipochat'],
    include_package_data=True,
    zip_safe=False,
    install_requires=['pika==0.9.13', 'tornado==3.2', 'redis'],
    entry_points={
        'console_scripts': [
            'hipo-chat = hipochat.chat:run',
        ],
    }
)
