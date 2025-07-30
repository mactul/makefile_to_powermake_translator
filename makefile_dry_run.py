import os
import shlex
import shutil
import subprocess

make_fullpath = shutil.which("make")
cmake_fullpath = shutil.which("cmake")

_cache_which = {}
def sh_which_cache(name: str):
    if name not in _cache_which:
        _cache_which[name] = shutil.which(name)
    return _cache_which[name]

def consume_command(command: str, i: int, stop_at_space: bool = False):
    in_string = 0
    escaped = False
    while i+1 < len(command) and (in_string or escaped or ((command[i] != '&' or command[i+1] != '&') and (not stop_at_space or command[i] != ' ' and command[i] != '\t'))):
        if not escaped and command[i] == '"' and in_string != 2:
            if in_string == 0:
                in_string = 1
            else:
                in_string = 0
        elif not escaped and command[i] == "'" and in_string != 1:
            if in_string == 0:
                in_string = 2
            else:
                in_string = 0

        if command[i] == '\\':
            escaped = True
        else:
            escaped = False

        i += 1

    if i+1 == len(command):
        i += 1
    return i

def split_commands_by_cwd(command: str, dir: str = "."):
    commands = []
    i = 0
    while i < len(command):
        s = i
        i = consume_command(command, i)

        parsed_command = shlex.split(command[s: i])
        if len(parsed_command) == 0:
            continue

        if parsed_command[0] == "cd":
            if len(parsed_command) < 2:
                dir = os.path.expanduser('~/')
            else:
                dir = os.path.join(dir, parsed_command[1])
        else:
            commands.append((dir, command[s: i]))

        while i < len(command) and command[i] == '&':
            i += 1
        while i < len(command) and (command[i] == ' ' or command[i] == '\t'):
            i += 1
    return commands

def neutralize_make(command: str):
    splitted_cmd = shlex.split(command)
    binary = splitted_cmd[0]
    if sh_which_cache(binary) == make_fullpath:
        return False, True, f"{binary} -n -B {command[consume_command(command, 0, True):]}"
    if sh_which_cache(binary) == cmake_fullpath:
        if len(splitted_cmd) >= 4 and splitted_cmd[1] == "-E" and splitted_cmd[2] == "cmake_link_script":
            return True, False, splitted_cmd[3]
        return True, False, None
    return False, False, command


def list_commands(commands: list[str], dir: str = "."):
    final_commands = []
    for command in commands:
        for cwd, cmd in split_commands_by_cwd(command, dir):
            cmake_found, make_found, neutralized_command = neutralize_make(cmd)
            if make_found:
                final_commands.extend(list_commands(subprocess.check_output(neutralized_command, shell=True, cwd=cwd).decode().split('\n'), dir))
            elif cmake_found:
                if neutralized_command is not None:
                    file = open(os.path.join(cwd, neutralized_command), "r")
                    final_commands.append((cwd, file.read().strip()))
                    file.close()
            else:
                final_commands.append((cwd, cmd))
    return final_commands

if __name__ == '__main__':
    commands = list_commands(["make"], "/home/mactul/Documents/c-cpp/boringssl/build")

    for cmd in commands:
        print(cmd)
        print()

    print(len(commands))