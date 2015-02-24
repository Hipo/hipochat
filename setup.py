from setuptools import setup

setup(
    name='hipochat',
    version='0.0.3',
    long_description=__doc__,
    packages=['hipochat'],
    include_package_data=True,
    zip_safe=False,
    install_requires=['pika==0.9.13', 'tornado==3.2', 'requests', 'redis'],
    entry_points = {
        'console_scripts': [
            'hipo-chat = hipochat.chat:run',
        ],
    }
)
