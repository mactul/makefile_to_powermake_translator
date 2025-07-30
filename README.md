# Makefile to PowerMake translator

This code is a proof of concept, the code is a mess, it's not reliable, not correctly typed.  
It's likely that we will see weird bugs with it, and it's expected that all Makefile can't be translated.

The idea is to have a tool that can help convert a complicated make or cmake build system to PowerMake by providing a first PowerMake that works or almost works.

It currently supports GNU Makefiles and CMake generated Makefiles but it doesn't work with automake generated makefiles.  
The makefile need to support `make -n -B` as a way of showing all commands and automake makefiles have a tendency to loop forever when run with `-B`.

It has been tested with BoringSSL (which uses CMake) and was able to successfully convert the generated Makefile set (3 files, 13000 lines) into a small (89 lines) fully working PowerMake.

Of course, PowerMake generated Makefiles are also easily translated back into PowerMake.

## How to proceed

First of all, if you are using cmake, you need to generate all the Makefiles.  
Usually, that's something like this:
```sh
cd project
mkdir build && cd build
cmake ..
```

Then, **you must run the Makefile**, this ensures that all objects are created and that make will not complain later when launched in dry-run mode.  
You may want to run the makefile with the `--no-builtin-rules` option to make sure that make doesn't delete intermediate objects (use the MAKEFLAGS environment variable for this setting to be recursive).

```sh
MAKEFLAGS=--no-builtin-rules make -j8
```

Once this is done, you can go in this folder and run:
```sh
python main.py /home/........./project/build
```

This will generate a `generated.py` that should in theory be able to compile the project.