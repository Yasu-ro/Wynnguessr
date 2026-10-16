package com.wynndle.panorama.mixin;

import net.minecraft.client.Minecraft;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.ModifyArg;

// Minecraft renders each face at 4096 and saves it shrunk 4 times (1024).
// Shrinking only 2 times keeps 2048 per face, enough for an 8192 panorama.
@Mixin(Minecraft.class)
public class PanoramaDownscaleMixin {
	@ModifyArg(method = "grabPanoramixScreenshot",
		at = @At(value = "INVOKE", target = "Lnet/minecraft/client/Screenshot;grab(Ljava/io/File;Ljava/lang/String;Lcom/mojang/blaze3d/pipeline/RenderTarget;ILjava/util/function/Consumer;)V"),
		index = 3)
	private int wynndle$downscale(int downscale) {
		return 2;
	}
}
