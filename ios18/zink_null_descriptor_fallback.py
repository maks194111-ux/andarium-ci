"""Give Zink real placeholder resources on Vulkan drivers without nullDescriptor.

Mesa removed this path when it began requiring robustness2.nullDescriptor.
Nothing is faked: unbound slots get a zeroed buffer / 1x1 zeroed image, and the
descriptor-buffer mode (which cannot express that) stays disabled.
"""
# SPDX-License-Identifier: MIT
import argparse
from pathlib import Path


def sub(path: Path, old: str, new: str, count: int = 1) -> None:
    text = path.read_text()
    found = text.count(old)
    if found != count:
        raise ValueError(f"{path.name}: expected {count} match(es), found {found}: {old!r}")
    path.write_text(text.replace(old, new))


NO_NULL = "!zink_screen(ctx->base.screen)->info.rb2_feats.nullDescriptor"

HELPER = r'''
/* placeholder resources for drivers without robustness2.nullDescriptor */
static bool
zink_init_dummy_descriptors(struct zink_context *ctx)
{
   struct zink_screen *screen = zink_screen(ctx->base.screen);
   static const uint8_t zeroes[4096] = {0};

   ctx->dummy_vertex_buffer = pipe_buffer_create(&screen->base,
      PIPE_BIND_VERTEX_BUFFER | PIPE_BIND_SHADER_IMAGE, PIPE_USAGE_IMMUTABLE, sizeof(zeroes));
   if (!ctx->dummy_vertex_buffer)
      return false;
   pipe_buffer_write_nooverlap(&ctx->base, ctx->dummy_vertex_buffer, 0, sizeof(zeroes), zeroes);
   struct zink_buffer_view *bv = get_buffer_view(ctx, zink_resource(ctx->dummy_vertex_buffer),
                                                 PIPE_FORMAT_R8G8B8A8_UNORM, 0, sizeof(zeroes));
   if (!bv)
      return false;
   ctx->dummy_bufferview = bv->buffer_view;

   struct pipe_resource templ = {0};
   templ.width0 = 1;
   templ.height0 = 1;
   templ.depth0 = 1;
   templ.array_size = 1;
   templ.format = PIPE_FORMAT_R8G8B8A8_UNORM;
   templ.target = PIPE_TEXTURE_2D;
   templ.bind = PIPE_BIND_RENDER_TARGET | PIPE_BIND_SAMPLER_VIEW | PIPE_BIND_SHADER_IMAGE;
   ctx->dummy_image = screen->base.resource_create(&screen->base, &templ);
   if (!ctx->dummy_image)
      return false;
   /* imageLoad on an unbound image must return 0 */
   struct pipe_box box = {0};
   box.width = box.height = box.depth = 1;
   ctx->base.texture_subdata(&ctx->base, ctx->dummy_image, 0, PIPE_MAP_WRITE, &box, zeroes, 4, 4);
   screen->image_barrier(ctx, zink_resource(ctx->dummy_image), VK_IMAGE_LAYOUT_GENERAL,
                         VK_ACCESS_SHADER_READ_BIT, VK_PIPELINE_STAGE_FRAGMENT_SHADER_BIT);
   struct pipe_surface stempl = {0};
   stempl.texture = ctx->dummy_image;
   stempl.format = PIPE_FORMAT_R8G8B8A8_UNORM;
   struct zink_surface *surf = zink_create_fb_surface(&ctx->base, &stempl);
   if (!surf)
      return false;
   ctx->dummy_image_view = surf->image_view;
   return true;
}
'''


def apply(mesa: Path) -> None:
    zink = mesa / "src/gallium/drivers/zink"
    c = zink / "zink_context.c"

    sub(zink / "zink_types.h",
        "   struct pipe_resource *dummy_xfb_buffer;\n",
        "   struct pipe_resource *dummy_xfb_buffer;\n"
        "   struct pipe_resource *dummy_vertex_buffer;\n"
        "   struct pipe_resource *dummy_image;\n"
        "   VkImageView dummy_image_view;\n"
        "   VkBufferView dummy_bufferview;\n")

    sub(zink / "zink_screen.c",
        "   if (!screen->info.rb2_feats.nullDescriptor) {\n"
        "      mesa_loge(\"Zink requires the nullDescriptor feature of KHR/EXT robustness2.\");\n"
        "      goto fail;\n"
        "   }\n\n", "")
    sub(zink / "zink_screen.c",
        "   bool can_db = true;\n   {\n",
        "   bool can_db = true;\n   {\n"
        "      if (!screen->info.rb2_feats.nullDescriptor) {\n"
        "         if (zink_descriptor_mode == ZINK_DESCRIPTOR_MODE_DB) {\n"
        "            if (!screen->driver_name_is_inferred)\n"
        "               mesa_loge(\"Cannot use db descriptor mode without robustness2.nullDescriptor\");\n"
        "            goto fail;\n"
        "         }\n"
        "         can_db = false;\n"
        "      }\n")

    sub(c, "   pipe_resource_reference(&ctx->dummy_xfb_buffer, NULL);\n",
        "   pipe_resource_reference(&ctx->dummy_xfb_buffer, NULL);\n"
        "   pipe_resource_reference(&ctx->dummy_vertex_buffer, NULL);\n"
        "   pipe_resource_reference(&ctx->dummy_image, NULL);\n")

    for kind in ("ubos", "ssbos"):
        sub(c, f"      ctx->di.t.{kind}[shader][slot].buffer = VK_NULL_HANDLE;\n",
            f"      ctx->di.t.{kind}[shader][slot].buffer = ctx->dummy_vertex_buffer ?\n"
            f"         zink_resource(ctx->dummy_vertex_buffer)->obj->buffer : VK_NULL_HANDLE;\n")

    sub(c,
        "      ctx->di.textures[shader][slot].imageView = VK_NULL_HANDLE;\n"
        "      ctx->di.textures[shader][slot].imageLayout = VK_IMAGE_LAYOUT_UNDEFINED;\n",
        "      ctx->di.textures[shader][slot].imageView = ctx->dummy_image_view;\n"
        "      ctx->di.textures[shader][slot].imageLayout = ctx->dummy_image_view ?\n"
        "         VK_IMAGE_LAYOUT_GENERAL : VK_IMAGE_LAYOUT_UNDEFINED;\n")
    sub(c, "         ctx->di.t.tbos[shader][slot] = VK_NULL_HANDLE;\n",
        "         ctx->di.t.tbos[shader][slot] = ctx->dummy_bufferview;\n")

    sub(c,
        "      memset(&ctx->di.images[shader][slot], 0, sizeof(ctx->di.images[shader][slot]));\n",
        "      memset(&ctx->di.images[shader][slot], 0, sizeof(ctx->di.images[shader][slot]));\n"
        "      if (ctx->dummy_image_view) {\n"
        "         ctx->di.images[shader][slot].imageView = ctx->dummy_image_view;\n"
        "         ctx->di.images[shader][slot].imageLayout = VK_IMAGE_LAYOUT_GENERAL;\n"
        "      }\n")
    sub(c, "         ctx->di.t.texel_images[shader][slot] = VK_NULL_HANDLE;\n",
        "         ctx->di.t.texel_images[shader][slot] = ctx->dummy_bufferview;\n")

    sub(c, "         buffers[i] = VK_NULL_HANDLE;\n         buffer_offsets[i] = 0;\n",
        "         buffers[i] = ctx->dummy_vertex_buffer ?\n"
        "            zink_resource(ctx->dummy_vertex_buffer)->obj->buffer : VK_NULL_HANDLE;\n"
        "         buffer_offsets[i] = 0;\n")

    sub(c, "         *bv = VK_NULL_HANDLE;\n", "         *bv = ctx->dummy_bufferview;\n")
    sub(c, "      memset(ii, 0, sizeof(*ii));\n",
        "      memset(ii, 0, sizeof(*ii));\n"
        "      if (ctx->dummy_image_view) {\n"
        "         ii->imageView = ctx->dummy_image_view;\n"
        "         ii->imageLayout = VK_IMAGE_LAYOUT_GENERAL;\n"
        "      }\n")

    sub(c, "ctx->di.fbfetch.imageView = VK_NULL_HANDLE;",
        "ctx->di.fbfetch.imageView = ctx->dummy_image_view;", count=2)

    sub(c,
        "struct pipe_context *\nzink_context_create(struct pipe_screen *pscreen, void *priv, unsigned flags)\n{\n",
        HELPER.lstrip("\n") +
        "\nstruct pipe_context *\nzink_context_create(struct pipe_screen *pscreen, void *priv, unsigned flags)\n{\n")
    sub(c,
        "   if (!is_copy_only) {\n"
        "      for (unsigned i = 0; i < MESA_SHADER_MESH_STAGES; i++) {\n"
        "         /* need to update these based on screen config for null descriptors */\n",
        "   if (!is_copy_only && !screen->info.rb2_feats.nullDescriptor &&\n"
        "       !zink_init_dummy_descriptors(ctx)) {\n"
        "      mesa_loge(\"ZINK: failed to create placeholder descriptor resources\");\n"
        "      goto fail;\n"
        "   }\n"
        "   if (!is_copy_only) {\n"
        "      for (unsigned i = 0; i < MESA_SHADER_MESH_STAGES; i++) {\n"
        "         /* need to update these based on screen config for null descriptors */\n")
    print("Applied Zink placeholder-descriptor fallback (descriptor-buffer mode disabled without nullDescriptor)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mesa", type=Path)
    apply(parser.parse_args().mesa)
