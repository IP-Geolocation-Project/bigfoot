Bigfoot
=======

``Bigfoot`` is a metaplatform for conducting active network measurements across multiple
measurement platforms. In the current iteration, ``Bigfoot`` supports the following
measurement platforms:

.. list-table::
   :header-rows: 1
   :widths: 30 25 25

   * - Platform
     - Measurements
     - Mode
   * - `RIPE Atlas <https://atlas.ripe.net>`_
     - ping
     - polling
   * - `CAIDA Ark <https://www.caida.org/projects/ark/>`_
     - ping
     - polling

Installation
------------

``Bigfoot`` was tested using **Python 3.14**. Currently, it can be installed from its GitHub
repository:

.. code-block:: bash

   pip install git+https://github.com/IP-Geolocation-Project/bigfoot.git

Usage
-----

This section describes the steps that should be followed to start ``Bigfoot`` and run a
measurement.

Startup
~~~~~~~

To use ``Bigfoot``, the following steps should be done on startup:

#. Create an instance of the :class:`~bigfoot.config.Config` class to define the runtime
   parameters. Depending on which drivers are used, a set of required parameters must be
   provided; see `Configuration parameters`_ for the full list.

   **RIPE Atlas**

   - To conduct measurements on **RIPE Atlas**, export the ``RIPE_API_KEY`` environment
     variable with the respective API key.

   **CAIDA Ark**

   - To conduct measurements on **CAIDA Ark**, set the ``GRPC_HOSTNAME`` and ``GRPC_PORT``
     parameters.

     - If the machine does not have a public domain name, set ``GRPC_HOSTNAME`` to
       ``localhost`` and create a tunnel to that machine using tunneling software such as
       ``ngrok``.

   - To interact with the Ark platform, the ``Bigfoot`` host runs a gRPC server. To start the
     server in **secure mode**, set the ``ARK_DAEMON_CERT_DIR`` parameter.

     - The directory given in ``ARK_DAEMON_CERT_DIR`` should contain ``fullchain.pem`` and
       ``privkey.pem`` in order to start the gRPC server in secure mode. By default, this
       parameter is set to ``None``, therefore the gRPC server will start in insecure mode.

   - Then, start the daemon client on the machine connected to the **Ark** platform,
     configured with the same hostname and port, and with the secure flag set to match the
     mode the gRPC server is running in. More details can be found in the
     `ark_daemon_client repository
     <https://github.com/IP-Geolocation-Project/ark_daemon_client>`_.

     - If tunneling software was used, set the hostname and port to the provided domain name
       and port.

#. Call :func:`~bigfoot.starter.start_system`, passing the instance of the
   :class:`~bigfoot.config.Config` class and the ``start_ripe_polling_driver`` /
   ``start_ark_polling_driver`` flags. This function will configure the runtime parameters
   across ``Bigfoot`` and start the respective drivers in daemon threads.

#. Optionally, call :func:`~bigfoot.logger.configure_logging` to enable logging across the
   system.

Running a measurement
~~~~~~~~~~~~~~~~~~~~~

Vantage points
^^^^^^^^^^^^^^

The :func:`~bigfoot.starter.start_system` function returns an instance of the
:class:`~bigfoot.vps.vp_manager.VantagePointManager` class, which stores the list of all
available vantage points across all used platforms. Two main methods are used to obtain the
names of the vantage points:

.. list-table::
   :header-rows: 1
   :widths: 40 60

   * - Method
     - Returns
   * - :meth:`~bigfoot.vps.vp_manager.VantagePointManager.get_vp_names`
     - Names of all vantage points across every platform.
   * - :meth:`~bigfoot.vps.vp_manager.VantagePointManager.get_vp_names_of_platform`
     - Names of vantage points from the specified platform (``'ripe'`` or ``'ark'``).

Measurement
^^^^^^^^^^^

A single measurement is managed by an instance of the
:class:`~bigfoot.measurements.measurement.Measurement` class created using three parameters:
a target, a set of vantage point names, and a measurement type. To conduct a measurement, the
:meth:`~bigfoot.measurements.measurement.Measurement.conduct_measurement` method of that
instance should be called. Once the measurement is completed, its results and status can be
obtained by accessing the attributes of that instance.

The measurement can finish with one of four statuses presented in the table below, in order of
precedence:

.. list-table::
   :header-rows: 1
   :widths: 22 78

   * - Status
     - Description
   * - ``FINISHED``
     - Every vantage point returned a valid RTT.
   * - ``UNACQUIRED``
     - At least one vantage point never cleared the rate limiter, which is used to prevent
       each vantage point from being overloaded. This status is obtained when too many
       measurements using the same vantage point were scheduled in a short window of time.
   * - ``TIMEOUT``
     - At least one vantage point returned nothing within the platform timeout.
   * - ``FAILED``
     - At least one vantage point returned an invalid RTT (``-1`` on RIPE Atlas).

See :class:`~bigfoot.measurements.measurement_status.MeasurementStatus` for the complete set
of statuses, including the intermediate ones a measurement passes through while running.

Example
~~~~~~~

The snippet below can be used to conduct a measurement using a hybrid set of vantage points.
More examples can be found in the *examples* directory.

.. code-block:: python

   from bigfoot import start_system, Measurement, Config, configure_logging
   import random

   # PRE-STARTUP:
   # You should start the Ark daemon client on the server with a direct connection to the Ark platform.

   # This function is used to configure the logging across the system. All submodules inherit this logger.
   # logger = configure_logging()

   # used to define the runtime parameters of the system.
   config = Config(
       RIPE_API_KEY='API_KEY',
       RIPE_MEASUREMENT_TIMEOUT=40,
       RIPE_POLLING_INTERVAL=10,

       GRPC_HOSTNAME='HOSTNAME',
       GRPC_PORT='PORT',
       ARK_DAEMON_CERT_DIR=None,  # if not None, the gRPC server will start in secure mode
       ARK_POLLING_INTERVAL=5,
       ARK_MEASUREMENT_TIMEOUT=20,
   )

   # start the system and get an instance of VantagePointManager.
   vp_manager = start_system(config, start_ripe_polling_driver=True, start_ark_polling_driver=True)

   # get the names of the vantage points from each measurement platform.
   ripe_vps = vp_manager.get_vp_names_of_platform(platform="ripe")
   ark_vps = vp_manager.get_vp_names_of_platform(platform="ark")

   # or get names of all vantage points by calling get_vp_names()
   all_vps = vp_manager.get_vp_names()

   print(f"There are {len(ripe_vps)} RIPE Atlas vantage points")
   print(f"There are {len(ark_vps)} ARK vantage points")

   # create a ping measurement with 3 RIPE Atlas and 3 ARK vantage points to 8.8.8.8.
   measurement = Measurement(
       target="8.8.8.8",
       vps=random.sample(ripe_vps, 3) + random.sample(ark_vps, 3),
       measurement_type="ping",
   )
   # conduct the measurement
   measurement.conduct_measurement()

   print(f"Measurement finished with status {measurement.status}")
   print(f"Results: {measurement.results}")

Configuration parameters
------------------------

Every runtime parameter is a keyword argument of the singleton
:class:`~bigfoot.config.Config` class, grouped into rate limiter, RIPE Atlas, CAIDA Ark and
metadata settings. See its API reference for the full list of parameters, types and defaults.

License
-------

This project is licensed under the MIT license.

.. toctree::
   :maxdepth: 4
   :caption: Reference

   api/modules
