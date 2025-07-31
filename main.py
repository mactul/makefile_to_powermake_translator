import os
import sys
import json
import glob
import shlex

import makefile_dry_run


def is_compiler(binary: str):
    return makefile_dry_run.sh_which_cache(binary).endswith((
        "-gcc",
        "/gcc",
        "-g++",
        "/g++",
        "-clang",
        "/clang",
        "-clang++",
        "/clang++",
        "-cc",
        "/cc",
        "-c++",
        "/c++"
    ))

def is_archiver(binary: str):
    return makefile_dry_run.sh_which_cache(binary).endswith(("-ar", "/ar"))


def is_so_version(string: str) -> bool:
    i = len(string) - 1
    while i > 0 and (string[i].isdigit() or string[i] == '.'):
        i -= 1
    if i <= 0:
        return False
    return string[:i+1].endswith(".so")


def all_startswith(files: list[str], prefix: str):
    for file in files:
        if not file.startswith(prefix):
            return False
    return True

def all_endswith(files: list[str], suffix: str):
    for file in files:
        if not file.endswith(suffix):
            return False
    return True

def one_match(files: list[str], prefix: str, suffix: str):
    for file in files:
        if file.startswith(prefix) and file.endswith(suffix):
            return True
    return False

def longest_prefix(files: list[str]):
    base = next(iter(files))
    i = 1
    while i <= len(base) and all_startswith(files, base[:i]):
        i += 1
    return base[:i-1]

def longest_suffix(files: list[str]):
    base = next(iter(files))
    i = len(base)-1
    while i >= 0 and all_endswith(files, base[i:]):
        i -= 1
    return base[i+1:]

def get_best_glob_match(files: list[str]):
    get_patterns = []
    filter_patterns = []

    files_grouped = {}
    for file in files:
        dir = os.path.dirname(file)
        if dir not in files_grouped:
            files_grouped[dir] = set()
        files_grouped[dir].add(os.path.basename(file))

    for dir in files_grouped:
        files_fullpath = set()
        for file in files_grouped[dir]:
            files_fullpath.add(os.path.join(dir, file))

        if len(files_grouped[dir]) == 1:
            get_patterns.append(next(iter(files_fullpath)))
            continue
        pattern = os.path.join(dir, longest_prefix(files_grouped[dir]) + '*' + longest_suffix(files_grouped[dir]))
        exceptions = set()
        files_in_dir = glob.glob(pattern, recursive=True)
        for file in files_in_dir:
            if file not in files:
                exceptions.add(file)
        if len(exceptions) != 0:
            if len(exceptions) == 1:
                get_patterns.append(pattern)
                filter_patterns.append(next(iter(exceptions)))
                continue
            filter_prefix = longest_prefix(exceptions)
            filter_suffix = longest_suffix(exceptions)
            if one_match(files_fullpath, filter_prefix, filter_suffix):
                # game over, we need to add each file one by one
                if len(files_fullpath) <= len(exceptions):
                    # It's more interesting to just add each file one by one
                    get_patterns.extend(files_fullpath)
                else:
                    # We will add each extension separately
                    filter_patterns.extend(exceptions)
                    get_patterns.append(pattern)
                continue
            filter_patterns.append(filter_prefix + '*' + filter_suffix)
        get_patterns.append(pattern)

    return get_patterns, filter_patterns


def flatten(l: list) -> list[str]:
    o = []
    for e in l:
        if isinstance(e, list):
            o.extend(flatten(e))
        else:
            o.append(e)
    return o


def extract_compiler_command(command: list[str], cwd: str):
    defines = []
    includedirs = []
    remaining_args = []
    inputfiles = []
    outputfile = None
    operation_type = "link"
    i = 1
    while i < len(command):
        if command[i] == "-D":
            i += 1
            if i < len(command) and command[i] not in ('NDEBUG', 'DEBUG'):
                defines.append(command[i])
        elif command[i].startswith("-D"):
            if command[i][2:] not in ('NDEBUG', 'DEBUG'):
                defines.append(command[i][2:])

        elif command[i] == "-I":
            i += 1
            if i < len(command):
                includedirs.append(command[i])
        elif command[i].startswith("-I"):
            includedirs.append(command[i][2:])

        elif command[i] == "-o":
            i += 1
            if i < len(command):
                if outputfile is not None:
                    raise RuntimeError("More than one outputfile was found")
                outputfile = os.path.join(cwd, command[i])
        elif command[i].startswith("-o"):
            if outputfile is not None:
                raise RuntimeError("More than one outputfile was found")
            outputfile = os.path.join(cwd, command[i][2:])

        elif command[i] == "-MF" or command[i] == "-MT" or command[i] == "-MQ":
            i += 1

        elif command[i].startswith("-"):
            if command[i] == '-c':
                operation_type = "compile"
            elif command[i] == "-shared":
                operation_type = "shared_link"
            elif command[i] not in ["-g", "-ggdb", "-fdiagnostics-color", "-O0", "-Og", "-O", "-O1", "-O2", "-O3", "-Os", "-Oz", "-Ofast", "-fomit-frame-pointer", "-M", "-MM", "-MG", "-MP", "-MD", "-MMD"] and not command[i].startswith("-Wl,--dependency-file="):
                remaining_args.append(command[i])
        else:
            inputfiles.append(os.path.join(cwd, command[i]))

        i += 1

    if operation_type == "compile":
        inputfiles = [file for file in inputfiles if file.endswith((".c", ".cpp", ".cc", ".C", ".s", ".S", ".asm", ".rc"))]

    return operation_type, defines, includedirs, remaining_args, inputfiles, outputfile

def extract_archiver_command(command: list[str], cwd: str):
    args = []
    inputfiles = []
    outputfile = None
    for el in command[1:]:
        if el.startswith("-"):
            arg = el.replace('r', '').replace('q', '').replace('c', '')
            if len(arg) > 0 and arg != '-':
                args.append(arg)
        elif el.endswith(".a"):
            outputfile = os.path.join(cwd, el)
        elif outputfile is not None:
            inputfiles.append(os.path.join(cwd, el))
        else:
            arg = el.replace('r', '').replace('q', '').replace('c', '')
            if len(arg) > 0 and arg != '-':
                args.append(arg)

    return "archive", args, inputfiles, outputfile

def check_deps(commands, i, current_num):
    for j in range(i, len(commands)):
        if commands[j][0] != current_num:
            # The parallelization is discontinued here, no need to look after
            return True
        if len(commands) < 6:
            continue  # can not happen, a non-compile command should break the parallelization
        if commands[i][6] in commands[j][5]:
            return False  # Our inputfile is used later, we need to break the parallelization
    return True


def used_unused(group, group_deps):
    required_files = set(flatten(file["dependencies"] for file in group["files"]))
    deps_files = {file["output"] for file in group_deps["files"]}

    return required_files.intersection(deps_files), deps_files.difference(required_files)



def create_compilation_groups(entries):
    commands = []

    commands_to_filters = (makefile_dry_run.sh_which_cache("mkdir") or "mkdir", makefile_dry_run.sh_which_cache("echo") or "echo", makefile_dry_run.sh_which_cache("printf") or "printf")
    _output_set = set()
    for entry in entries:
        outputfile = None
        command = shlex.split(entry[1])
        if len(command) == 0:
            continue
        if is_compiler(command[0]):
            cmd = [0, *extract_compiler_command(command, entry[0])]
            outputfile = cmd[6]
        elif is_archiver(command[0]):
            cmd = [0, *extract_archiver_command(command, entry[0])]
            outputfile = cmd[4]
        elif makefile_dry_run.sh_which_cache(command[0]) in commands_to_filters:
            # don't keep mkdir, echo and printf, PowerMake will do most of them anyway
            continue
        else:
            commands.append([0, entry[1], entry[0]])
            continue

        if outputfile is not None and outputfile not in _output_set:
            _output_set.add(outputfile)
            commands.append(cmd)

    current_num = 0
    for i in range(len(commands)-1, -1, -1):
        if len(commands[i]) == 2 or commands[i][1] != "compile":
            current_num += 1
            commands[i][0] = current_num
            current_num += 1
            continue
        if not check_deps(commands, i, current_num):
            current_num += 1
        commands[i][0] = current_num

    commands.sort(reverse=True)

    groups = []

    group_n = -1
    group_template = None

    for command in commands:
        if len(command) == 3:
            groups.append({"operation_type": "command", "defines": [], "includedirs": [], "args": [], "files": [], "command": command[1], "command_cwd": command[2]})
            group_n += 1
            group_template = command
            continue
        if command[1] == "archive":
            groups.append({"operation_type": "archive", "defines": [], "includedirs": [], "args": command[2], "files": [{"dependencies": command[3], "output": command[4]}], "command": None, "command_cwd": None})
            group_n += 1
            group_template = command
            continue
        if group_template is None or group_template[:5] != command[:5] or command[1] != "compile":
            groups.append({"operation_type": command[1], "defines": command[2], "includedirs": command[3], "args": command[4], "files": [], "command": None, "command_cwd": None})
            group_n += 1
            group_template = command
        groups[group_n]["files"].append({"dependencies": command[5], "output": command[6]})

    i = 0
    while i < len(groups):
        must_split = False
        used = set()
        unused = set()
        for j in range(i, len(groups)):
            used, unused = used_unused(groups[j], groups[i])
            if len(used) > 0 and len(unused) > 0:
                must_split = True
                break
        if must_split:
            group = groups.pop(i)
            group1 = {"operation_type": group["operation_type"], "defines": group["defines"], "includedirs": group["includedirs"], "args": group["args"], "command": group["command"], "command_cwd": group["command_cwd"], "files": []}
            group2 = {**group1, "files": []}
            for file in group["files"]:
                if file["output"] in used:
                    group1["files"].append(file)
                else:
                    group2["files"].append(file)
            groups.insert(i, group1)
            groups.insert(i, group2)
        else:
            i += 1

    return groups

def create_instructions(groups):
    instructions: list[str] = []
    last_function_state = {"defines": [], "includedirs": [], "c_flags": [], "cpp_flags": [], "as_flags": [], "asm_flags": [], "rc_flags": [], "ld_flags": [], "shared_linker_flags": [], "ar_flags": []}
    archives_variables = {}
    archives_var_counter = 0
    shared_libs_variables = {}
    shared_libs_var_counter = 0
    objects_variables = {}
    objects_var_counter = 0
    project_name = None
    instructions_count = 0
    for group in groups:
        function_state = {**last_function_state}

        instructions_count += len(group["files"])

        if group["operation_type"] == "command":
            instructions.append(f"powermake.run_command(config, {json.dumps(group['command'])}, shell=True, cwd={json.dumps(group['command_cwd'])})")
            print("\033[0;33mWarning:\033[0;m Verify this line in the generated powermake:")
            print(f"\033[2;37m{instructions[-1]}\033[0;m")
            continue

        elif group["operation_type"] == "compile":
            function_state["defines"] = group["defines"]
            function_state["includedirs"] = group["includedirs"]
            for file in group["files"]:
                for dep in file["dependencies"]:
                    if dep.endswith(".c"):
                        function_state["c_flags"] = group["args"]
                    elif dep.endswith((".cpp", ".cc", ".C")):
                        function_state["cpp_flags"] = group["args"]
                    elif dep.endswith((".s", ".S")):
                        function_state["as_flags"] = group["args"]
                    elif dep.endswith(".asm"):
                        function_state["asm_flags"] = group["args"]
                    elif dep.endswith(".rc"):
                        function_state["rc_flags"] = group["args"]
                    else:
                        print("error, unhandled file extension:", dep)
                        exit(1)
        elif group["operation_type"] == "link":
            function_state["ld_flags"] = group["args"]
        elif group["operation_type"] == "shared_link":
            function_state["shared_linker_flags"] = group["args"]
        elif group["operation_type"] == "archive":
            function_state["ar_flags"] = group["args"]

        for key in last_function_state:
            to_add = set(function_state[key]).difference(last_function_state[key])
            to_remove = set(last_function_state[key]).difference(function_state[key])
            if len(to_add) > 0:
                instructions.append(f"config.add_{key}({str([arg for arg in function_state[key] if arg in to_add])[1:-1]})")
            if len(to_remove) > 0:
                instructions.append(f"config.remove_{key}({str(to_remove)[1:-1]})")

        if group["operation_type"] == "compile":
            to_get, to_filter = get_best_glob_match(flatten([file["dependencies"] for file in group["files"]]))

            if len(to_filter) == 0:
                instructions.append("files = powermake.get_files(" + str(to_get)[1:-1] + ")")
            else:
                instructions.append("files = powermake.filter_files(powermake.get_files(" + str(to_get)[1:-1] + "), " + str(to_filter)[1:-1] + ")")

            objects_var_counter += 1
            objects_variables[f"objects{objects_var_counter}"] = {file["output"] for file in group["files"]}
            instructions.append(f"objects{objects_var_counter} = powermake.compile_files(config, files)")

        else:
            target_name = os.path.splitext(os.path.basename(next(iter(group["files"]))["output"]))[0]
            if project_name is None:
                project_name = target_name
            variables_names = set()
            variables_union = set()
            count = objects_var_counter
            required_mixed = flatten([file["dependencies"] for file in group["files"]])
            required_objects = {obj for obj in required_mixed if not obj.endswith(".a") and not is_so_version(obj)}
            required_archives = [os.path.splitext(os.path.basename(archive))[0] for archive in required_mixed if archive.endswith(".a")]
            required_shared_libs = [os.path.splitext(os.path.basename(lib))[0] for lib in required_mixed if is_so_version(lib)]

            archives_variables_list = []
            for archive in required_archives:
                if archive in archives_variables:
                    archives_variables_list.append(archives_variables[archive])
            for lib in required_shared_libs:
                if lib in shared_libs_variables:
                    archives_variables_list.append(shared_libs_variables[lib])

            while count > 0 and len(required_objects.difference(variables_union)) > 0:
                if len(objects_variables[f"objects{count}"].intersection(required_objects)) > 0 and len(objects_variables[f"objects{count}"].difference(variables_union)) > 0:
                    variables_names.add(f"objects{count}")
                    variables_union.update(objects_variables[f"objects{count}"])
                count -= 1
            diffs = required_objects.difference(variables_union)
            if len(diffs) > 0:
                to_get, to_filter = get_best_glob_match(diffs)
                objects_var_counter += 1
                if len(to_filter) == 0:
                    instructions.append(f"objects{objects_var_counter} = powermake.get_files(" + str(to_get)[1:-1] + ")")
                else:
                    instructions.append(f"objects{objects_var_counter} = powermake.filter_files(powermake.get_files(" + str(to_get)[1:-1] + "), " + str(to_filter)[1:-1] + ")")
                objects_variables[f"objects{objects_var_counter}"] = diffs
                variables_names.add(f"objects{objects_var_counter}")

            if len(variables_names) < 1:
                print("fatal error")
                exit(1)
            objects_var = next(iter(variables_names))
            variables_names.remove(objects_var)
            if len(variables_names) > 0:
                objects_var = f"{objects_var}.union("
                for name in variables_names:
                    objects_var += name + ", "
                objects_var = objects_var[:-2] + ')'

            archives_list_str = ""
            if len(archives_variables_list) > 0:
                for archive in archives_variables_list:
                    archives_list_str += archive + ", "
                archives_list_str = ", archives=[" + archives_list_str[:-2] + "]"

            if group["operation_type"] == "link" or group["operation_type"] == "unknown":
                project_name = target_name
                instructions.append(f"powermake.link_files(config, {objects_var}{archives_list_str}, executable_name={json.dumps(target_name)})")
            elif group["operation_type"] == "shared_link":
                shared_libs_var_counter += 1
                shared_libs_variables[target_name] = f"shared_lib{shared_libs_var_counter}"
                instructions.append(f"shared_lib{shared_libs_var_counter} = powermake.link_shared_lib(config, {objects_var}{archives_list_str}, lib_name={json.dumps(target_name)})")
            elif group["operation_type"] == "archive":
                archives_var_counter += 1
                archives_variables[target_name] = f"archives{archives_var_counter}"
                instructions.append(f"archives{archives_var_counter} = powermake.archive_files(config, {objects_var}, archive_name={json.dumps(target_name)})")


        last_function_state = function_state

    return project_name, instructions_count, instructions


def generate_code(makefile_folder):
    entries = makefile_dry_run.list_commands(["make"], makefile_folder)
    groups = create_compilation_groups(entries)


    project_name, instructions_count, instructions = create_instructions(groups)
    if project_name is None:
        project_name = "PROJECT_NAME"

    code = "import powermake\n\n\n"

    code += "def on_build(config: powermake.Config):\n"
    code += f"    config.nb_total_operations = {instructions_count}\n\n"
    for instruction in instructions:
        code += f"    {instruction}\n\n"

    code += f"\n\npowermake.run({json.dumps(project_name)}, build_callback=on_build)\n"

    return code


if __name__ == "__main__":
    print("====================================================")
    print("==        Experimental PowerMake generator        ==")
    print("==                                                ==")
    print("==       This Program is not 100% reliable,       ==")
    print("==      it will try to generate a PowerMake,      ==")
    print("==   but you have to verify the generated file.   ==")
    print("==    Watch out for the `powermake.run_command`   ==")
    print("==     lines, they will most likely be wrong.     ==")
    print("====================================================\n")

    if len(sys.argv) > 1:
        makefile_folder = sys.argv[1]
    else:
        makefile_folder = input("Enter makefile's folder path: ")

    code = generate_code(makefile_folder)
    with open("generated.py", "w") as file:
        file.write(code)

