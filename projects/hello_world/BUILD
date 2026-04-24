load("@rules_cc//cc:defs.bzl", "cc_binary", "cc_library", "cc_test")

cc_library(
    name = "hello_lib",
    srcs = ["hello_lib.cc"],
    hdrs = ["hello_lib.h"],
    visibility = ["//visibility:public"],
)

cc_binary(
    name = "hello_world",
    srcs = ["main.cc"],
    deps = [":hello_lib"],
)

cc_test(
    name = "hello_test",
    srcs = ["hello_test.cc"],
    deps = [":hello_lib"],
)
