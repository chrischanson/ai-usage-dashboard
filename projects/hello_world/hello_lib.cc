#include "hello_lib.h"

namespace hello {
std::string get_greeting(const std::string& name) {
    return "Hello, " + name + "!";
}
} // namespace hello
