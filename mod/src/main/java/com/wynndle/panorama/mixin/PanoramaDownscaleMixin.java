package com.wynndle.panorama.mixin;

import net.minecraft.client.Minecraft;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.ModifyArg;

// Minecraft renders each face at 4096 and saves it shrunk 4 times (1024).
// Not shrinking keeps the full 4096 per face: the site shows them as
// multires tiles, as sharp as the game renders them.
@Mixin(Minecraft.class)
public class PanoramaDownscaleMixin {
	@ModifyArg(method = "grabPanoramixScreenshot",
		at = @At(value = "INVOKE", target = "Lnet/minecraft/client/Screenshot;grab(Ljava/io/File;Ljava/lang/String;Lcom/mojang/blaze3d/pipeline/RenderTarget;ILjava/util/function/Consumer;)V"),
		index = 3)
	private int wynndle$downscale(int downscale) {
		return 1;
	}
}
