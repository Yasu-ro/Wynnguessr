package com.wynndle.panorama.mixin;

import com.wynndle.panorama.WynndlePanorama;
import net.minecraft.client.renderer.entity.EntityRenderer;
import net.minecraft.client.renderer.entity.state.EntityRenderState;
import net.minecraft.world.entity.Entity;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfo;

// During a capture, no entity shows a name above it (labels on armor stands).
@Mixin(EntityRenderer.class)
public class HideNamesMixin {
	@Inject(method = "extractRenderState", at = @At("TAIL"))
	private void wynndle$noName(Entity entity, EntityRenderState state, float partialTick, CallbackInfo ci) {
		if (WynndlePanorama.capturing) state.nameTag = null;
	}
}
