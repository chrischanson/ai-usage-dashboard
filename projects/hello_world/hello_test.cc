#include <iostream>
#include "hello_lib.h"

int main() {
    if (hello::get_greeting("Test") != "Hello, Test!") {
        std::cerr << "Test failed: expected 'Hello, Test!', got '" << hello::get_greeting("Test") << "'" << std::endl;
        return 1;
    }
    if (hello::get_greeting("") != "Hello, !") {
        std::cerr << "Test failed: expected 'Hello, !', got '" << hello::get_greeting("") << "'" << std::endl;
        return 1;
    }
    std::cout << "All tests passed!" << std::endl;
    return 0;
}
