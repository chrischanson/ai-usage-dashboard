#include <gtest/gtest.h>
#include "hello_lib.h"

TEST(HelloLibTest, GreetsWithName) {
    EXPECT_EQ(hello::get_greeting("Test"), "Hello, Test!");
}

TEST(HelloLibTest, GreetsWithEmptyName) {
    EXPECT_EQ(hello::get_greeting(""), "Hello, !");
}

TEST(HelloLibTest, GreetsWorld) {
    EXPECT_EQ(hello::get_greeting("World"), "Hello, World!");
}
