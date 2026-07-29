#include <mach-o/dyld.h>
#include <libgen.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

int main(int argc, char *argv[]) {
    char exe[4096];
    uint32_t size = sizeof(exe);

    if (_NSGetExecutablePath(exe, &size) != 0) {
        return 1;
    }

    char *dir = dirname(exe);
    char script[4096];

    if (snprintf(script, sizeof(script), "%s/../Resources/run.sh", dir) >= (int)sizeof(script)) {
        return 1;
    }

    execl("/bin/bash", "bash", script, (char *)NULL);
    perror("execl");
    return 1;
}
