// SPDX-License-Identifier: MIT
// Standalone candidate-driver probe, NOT an Andarium renderer replacement.
#include <vulkan/vulkan.h>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <vector>

static void check(VkResult result, const char* operation) {
    if (result != VK_SUCCESS) {
        std::fprintf(stderr, "%s failed: VkResult %d\n", operation, result);
        std::exit(1);
    }
}

int main() {
    uint32_t instanceExtensionCount = 0;
    check(vkEnumerateInstanceExtensionProperties(nullptr, &instanceExtensionCount, nullptr),
          "enumerate instance extensions");
    std::vector<VkExtensionProperties> instanceProperties(instanceExtensionCount);
    check(vkEnumerateInstanceExtensionProperties(nullptr, &instanceExtensionCount, instanceProperties.data()),
          "read instance extensions");
    bool hasPortabilityEnumeration = false;
    for (const auto& extension : instanceProperties)
        hasPortabilityEnumeration |= !std::strcmp(extension.extensionName,
                                                  VK_KHR_PORTABILITY_ENUMERATION_EXTENSION_NAME);
    // This test links the ICD directly, not the Vulkan loader. Enumeration
    // is a loader extension and must not be requested from an ICD lacking it.
    std::printf("Portability enumeration extension: %s\n",
                hasPortabilityEnumeration ? "enabled" : "absent; direct ICD enumeration");
    const char* instanceExtensions[] = {VK_KHR_PORTABILITY_ENUMERATION_EXTENSION_NAME};
    VkApplicationInfo application{VK_STRUCTURE_TYPE_APPLICATION_INFO};
    application.pApplicationName = "Andarium compatibility probe";
    application.apiVersion = VK_API_VERSION_1_1;
    VkInstanceCreateInfo create{VK_STRUCTURE_TYPE_INSTANCE_CREATE_INFO};
    create.pApplicationInfo = &application;
    create.flags = hasPortabilityEnumeration ? VK_INSTANCE_CREATE_ENUMERATE_PORTABILITY_BIT_KHR : 0;
    create.enabledExtensionCount = hasPortabilityEnumeration ? 1 : 0;
    create.ppEnabledExtensionNames = instanceExtensions;
    VkInstance instance{};
    check(vkCreateInstance(&create, nullptr, &instance), "create instance");
    uint32_t count = 0;
    check(vkEnumeratePhysicalDevices(instance, &count, nullptr), "enumerate count");
    if (!count) { std::fprintf(stderr, "No Vulkan device\n"); return 1; }
    std::vector<VkPhysicalDevice> devices(count);
    check(vkEnumeratePhysicalDevices(instance, &count, devices.data()), "enumerate devices");
    const auto physical = devices.front();
    VkPhysicalDeviceProperties properties{};
    vkGetPhysicalDeviceProperties(physical, &properties);
    std::printf("Vulkan API: %u.%u.%u\n", VK_API_VERSION_MAJOR(properties.apiVersion),
                VK_API_VERSION_MINOR(properties.apiVersion), VK_API_VERSION_PATCH(properties.apiVersion));
    uint32_t extensionCount = 0;
    check(vkEnumerateDeviceExtensionProperties(physical, nullptr, &extensionCount, nullptr),
          "enumerate extension count");
    std::vector<VkExtensionProperties> extensions(extensionCount);
    check(vkEnumerateDeviceExtensionProperties(physical, nullptr, &extensionCount, extensions.data()),
          "enumerate extensions");
    const auto has = [&](const char* name) {
        for (const auto& extension : extensions)
            if (!std::strcmp(extension.extensionName, name)) return true;
        return false;
    };
    for (const char* name : {"VK_EXT_external_memory_host", "VK_EXT_external_memory_metal",
                            "VK_EXT_metal_objects", "VK_EXT_image_drm_format_modifier",
                            "VK_EXT_transform_feedback", "VK_KHR_timeline_semaphore"})
        std::printf("%s: %s\n", name, has(name) ? "available" : "absent");
    uint32_t queueCount = 0;
    vkGetPhysicalDeviceQueueFamilyProperties(physical, &queueCount, nullptr);
    std::vector<VkQueueFamilyProperties> families(queueCount);
    vkGetPhysicalDeviceQueueFamilyProperties(physical, &queueCount, families.data());
    uint32_t family = queueCount;
    for (uint32_t i = 0; i < queueCount; ++i)
        if (families[i].queueCount && (families[i].queueFlags & VK_QUEUE_GRAPHICS_BIT)) {
            family = i; break;
        }
    if (family == queueCount) { std::fprintf(stderr, "No graphics queue\n"); return 1; }
    const float priority = 1;
    VkDeviceQueueCreateInfo queueInfo{VK_STRUCTURE_TYPE_DEVICE_QUEUE_CREATE_INFO};
    queueInfo.queueFamilyIndex = family;
    queueInfo.queueCount = 1;
    queueInfo.pQueuePriorities = &priority;
    const char* portability = "VK_KHR_portability_subset";
    VkDeviceCreateInfo deviceInfo{VK_STRUCTURE_TYPE_DEVICE_CREATE_INFO};
    deviceInfo.queueCreateInfoCount = 1;
    deviceInfo.pQueueCreateInfos = &queueInfo;
    deviceInfo.enabledExtensionCount = has(portability) ? 1 : 0;
    deviceInfo.ppEnabledExtensionNames = &portability;
    VkDevice device{};
    check(vkCreateDevice(physical, &deviceInfo, nullptr, &device), "create device");
    VkQueue queue{};
    vkGetDeviceQueue(device, family, 0, &queue);
    VkBufferCreateInfo bufferInfo{VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO};
    bufferInfo.size = 4096;
    bufferInfo.usage = VK_BUFFER_USAGE_TRANSFER_DST_BIT;
    VkBuffer buffer{};
    check(vkCreateBuffer(device, &bufferInfo, nullptr, &buffer), "create buffer");
    VkMemoryRequirements requirements{};
    vkGetBufferMemoryRequirements(device, buffer, &requirements);
    VkPhysicalDeviceMemoryProperties memory{};
    vkGetPhysicalDeviceMemoryProperties(physical, &memory);
    uint32_t memoryIndex = memory.memoryTypeCount;
    for (uint32_t i = 0; i < memory.memoryTypeCount; ++i) {
        const auto needed = VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT | VK_MEMORY_PROPERTY_HOST_COHERENT_BIT;
        if ((requirements.memoryTypeBits & (1u << i)) &&
            (memory.memoryTypes[i].propertyFlags & needed) == needed) { memoryIndex = i; break; }
    }
    if (memoryIndex == memory.memoryTypeCount) {
        std::fprintf(stderr, "No host-visible coherent memory\n"); return 1;
    }
    VkMemoryAllocateInfo allocation{VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO};
    allocation.allocationSize = requirements.size;
    allocation.memoryTypeIndex = memoryIndex;
    VkDeviceMemory storage{};
    check(vkAllocateMemory(device, &allocation, nullptr, &storage), "allocate");
    check(vkBindBufferMemory(device, buffer, storage, 0), "bind");
    VkCommandPoolCreateInfo poolInfo{VK_STRUCTURE_TYPE_COMMAND_POOL_CREATE_INFO};
    poolInfo.queueFamilyIndex = family;
    VkCommandPool pool{};
    check(vkCreateCommandPool(device, &poolInfo, nullptr, &pool), "command pool");
    VkCommandBufferAllocateInfo commandInfo{VK_STRUCTURE_TYPE_COMMAND_BUFFER_ALLOCATE_INFO};
    commandInfo.commandPool = pool;
    commandInfo.commandBufferCount = 1;
    VkCommandBuffer command{};
    check(vkAllocateCommandBuffers(device, &commandInfo, &command), "command allocation");
    VkCommandBufferBeginInfo begin{VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO};
    check(vkBeginCommandBuffer(command, &begin), "begin");
    constexpr uint32_t marker = 0x18AADA55;
    vkCmdFillBuffer(command, buffer, 0, 4096, marker);
    VkBufferMemoryBarrier barrier{VK_STRUCTURE_TYPE_BUFFER_MEMORY_BARRIER};
    barrier.srcAccessMask = VK_ACCESS_TRANSFER_WRITE_BIT;
    barrier.dstAccessMask = VK_ACCESS_HOST_READ_BIT;
    barrier.srcQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED;
    barrier.dstQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED;
    barrier.buffer = buffer;
    barrier.size = VK_WHOLE_SIZE;
    vkCmdPipelineBarrier(command, VK_PIPELINE_STAGE_TRANSFER_BIT, VK_PIPELINE_STAGE_HOST_BIT,
                         0, 0, nullptr, 1, &barrier, 0, nullptr);
    check(vkEndCommandBuffer(command), "end");
    VkFenceCreateInfo fenceInfo{VK_STRUCTURE_TYPE_FENCE_CREATE_INFO};
    VkFence fence{};
    check(vkCreateFence(device, &fenceInfo, nullptr, &fence), "fence");
    VkSubmitInfo submit{VK_STRUCTURE_TYPE_SUBMIT_INFO};
    submit.commandBufferCount = 1;
    submit.pCommandBuffers = &command;
    check(vkQueueSubmit(queue, 1, &submit, fence), "submit");
    check(vkWaitForFences(device, 1, &fence, VK_TRUE, 10000000000ULL), "wait (10 seconds)");
    void* mapped{};
    check(vkMapMemory(device, storage, 0, VK_WHOLE_SIZE, 0, &mapped), "map");
    bool verified = true;
    for (size_t i = 0; i < 1024; ++i)
        verified &= static_cast<const uint32_t*>(mapped)[i] == marker;
    vkUnmapMemory(device, storage);
    vkDestroyFence(device, fence, nullptr);
    vkDestroyCommandPool(device, pool, nullptr);
    vkDestroyBuffer(device, buffer, nullptr);
    vkFreeMemory(device, storage, nullptr);
    vkDestroyDevice(device, nullptr);
    vkDestroyInstance(instance, nullptr);
    std::puts(verified ? "PASS: GPU buffer fill and readback" : "FAIL: GPU buffer readback mismatch");
    std::puts("Not an Android boot, rendering, iOS device or performance test.");
    return verified ? 0 : 1;
}
