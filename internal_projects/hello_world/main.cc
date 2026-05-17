#include <iostream>
#include "hello_lib.h"

int main() {
    std::cout << hello::get_greeting("World") << std::endl;
    return 0;
}
