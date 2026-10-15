package com.wynndle.panorama;

import com.mojang.blaze3d.platform.InputConstants;
import net.fabricmc.api.ClientModInitializer;
import net.fabricmc.fabric.api.client.event.lifecycle.v1.ClientTickEvents;
import net.fabricmc.fabric.api.client.keybinding.v1.KeyBindingHelper;
import net.fabricmc.loader.api.FabricLoader;
import net.minecraft.ChatFormatting;
import net.minecraft.client.KeyMapping;
import net.minecraft.client.Minecraft;
import net.minecraft.client.player.LocalPlayer;
import net.minecraft.network.chat.Component;
import org.lwjgl.glfw.GLFW;

import javax.imageio.IIOImage;
import javax.imageio.ImageIO;
import javax.imageio.ImageWriteParam;
import javax.imageio.ImageWriter;
import javax.imageio.stream.ImageOutputStream;
import java.awt.image.BufferedImage;
import java.io.File;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Comparator;
import java.util.stream.Stream;

// One key: Minecraft's own panorama (6 cube faces, world only, no GUI),
// stitched into a 4096x2048 equirectangular image, the format wynndle.com
// shows with Pannellum. The file is named X_Z after the player's block.
public class WynndlePanorama implements ClientModInitializer {
	static final int WIDTH = 4096, HEIGHT = 2048;

	static KeyMapping key;
	static volatile boolean busy;

	@Override
	public void onInitializeClient() {
		key = KeyBindingHelper.registerKeyBinding(new KeyMapping(
			"key.wynndle-panorama.capture", InputConstants.Type.KEYSYM, GLFW.GLFW_KEY_F7, KeyMapping.Category.MISC));
		ClientTickEvents.END_CLIENT_TICK.register(mc -> {
			while (key.consumeClick()) {
				if (mc.player != null && mc.level != null && !busy) capture(mc);
			}
		});
	}

	static void capture(Minecraft mc) {
		LocalPlayer p = mc.player;
		int x = p.getBlockX(), z = p.getBlockZ();
		Path out = FabricLoader.getInstance().getGameDir().resolve("wynndle");
		Path tmp = out.resolve(".tmp-" + System.currentTimeMillis());

		// Every image faces north in its centre, whatever way the player looks.
		float yaw = p.getYRot(), yawO = p.yRotO;
		p.setYRot(180f);
		p.yRotO = 180f;
		try {
			Files.createDirectories(tmp);
			mc.grabPanoramixScreenshot(tmp.toFile());
		} catch (IOException e) {
			say(mc, Component.literal("Wynndle: " + e.getMessage()).withStyle(ChatFormatting.RED));
			return;
		} finally {
			p.setYRot(yaw);
			p.yRotO = yawO;
		}

		busy = true;
		say(mc, Component.literal("Wynndle: saving " + x + " " + z + "…").withStyle(ChatFormatting.GRAY));
		Thread t = new Thread(() -> {
			try {
				BufferedImage[] faces = readFaces(tmp.resolve("screenshots"));
				File file = freeName(out, x + "_" + z);
				writeJpeg(stitch(faces), file);
				say(mc, Component.literal("Wynndle: " + file.getName() + " saved").withStyle(ChatFormatting.GREEN));
			} catch (Exception e) {
				say(mc, Component.literal("Wynndle: failed (" + e.getMessage() + ")").withStyle(ChatFormatting.RED));
			} finally {
				deleteTree(tmp);
				busy = false;
			}
		}, "wynndle-panorama");
		t.setDaemon(true);
		t.start();
	}

	// Minecraft writes the faces asynchronously: wait until all six read back.
	static BufferedImage[] readFaces(Path dir) throws Exception {
		BufferedImage[] faces = new BufferedImage[6];
		long deadline = System.currentTimeMillis() + 60_000;
		for (int i = 0; i < 6; i++) {
			File f = dir.resolve("panorama_" + i + ".png").toFile();
			while (true) {
				try {
					if (f.isFile()) faces[i] = ImageIO.read(f);
				} catch (IOException ignored) {
					// still being written
				}
				if (faces[i] != null) break;
				if (System.currentTimeMillis() > deadline) throw new IOException("face " + i + " missing");
				Thread.sleep(200);
			}
		}
		return faces;
	}

	// Face order is Minecraft's: front (north here), +90° (east), +180° (south),
	// -90° (west), up, down. Vectors are (east, up, north).
	static final double[][][] FACES = {
		{{0, 0, 1}, {1, 0, 0}, {0, 1, 0}},
		{{1, 0, 0}, {0, 0, -1}, {0, 1, 0}},
		{{0, 0, -1}, {-1, 0, 0}, {0, 1, 0}},
		{{-1, 0, 0}, {0, 0, 1}, {0, 1, 0}},
		{{0, 1, 0}, {1, 0, 0}, {0, 0, -1}},
		{{0, -1, 0}, {1, 0, 0}, {0, 0, 1}},
	}; // {forward, right, screen up}

	static BufferedImage stitch(BufferedImage[] faces) {
		int size = faces[0].getWidth();
		int[][] px = new int[6][];
		for (int i = 0; i < 6; i++) px[i] = faces[i].getRGB(0, 0, size, size, null, 0, size);

		BufferedImage img = new BufferedImage(WIDTH, HEIGHT, BufferedImage.TYPE_INT_RGB);
		int[] row = new int[WIDTH];
		for (int v = 0; v < HEIGHT; v++) {
			double lat = (0.5 - (v + 0.5) / HEIGHT) * Math.PI;
			for (int u = 0; u < WIDTH; u++) {
				double lon = ((u + 0.5) / WIDTH - 0.5) * 2 * Math.PI;
				double[] d = {Math.cos(lat) * Math.sin(lon), Math.sin(lat), Math.cos(lat) * Math.cos(lon)};
				int best = 0;
				double bestDot = -2;
				for (int f = 0; f < 6; f++) {
					double dot = dot(FACES[f][0], d);
					if (dot > bestDot) { bestDot = dot; best = f; }
				}
				double sx = dot(FACES[best][1], d) / bestDot, sy = -dot(FACES[best][2], d) / bestDot;
				row[u] = bilinear(px[best], size, (sx + 1) / 2 * size - 0.5, (sy + 1) / 2 * size - 0.5);
			}
			img.setRGB(0, v, WIDTH, 1, row, 0, WIDTH);
		}
		return img;
	}

	static double dot(double[] a, double[] b) {
		return a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
	}

	static int bilinear(int[] px, int size, double x, double y) {
		x = Math.max(0, Math.min(size - 1, x));
		y = Math.max(0, Math.min(size - 1, y));
		int x0 = (int) x, y0 = (int) y, x1 = Math.min(x0 + 1, size - 1), y1 = Math.min(y0 + 1, size - 1);
		double fx = x - x0, fy = y - y0;
		int a = px[y0 * size + x0], b = px[y0 * size + x1], c = px[y1 * size + x0], e = px[y1 * size + x1];
		int rgb = 0;
		for (int s = 16; s >= 0; s -= 8) {
			double top = ((a >> s) & 255) * (1 - fx) + ((b >> s) & 255) * fx;
			double bot = ((c >> s) & 255) * (1 - fx) + ((e >> s) & 255) * fx;
			rgb |= ((int) Math.round(top * (1 - fy) + bot * fy)) << s;
		}
		return rgb;
	}

	static File freeName(Path dir, String base) throws IOException {
		Files.createDirectories(dir);
		File f = dir.resolve(base + ".jpg").toFile();
		for (int n = 2; f.exists(); n++) f = dir.resolve(base + "_" + n + ".jpg").toFile();
		return f;
	}

	static void writeJpeg(BufferedImage img, File file) throws IOException {
		ImageWriter w = ImageIO.getImageWritersByFormatName("jpg").next();
		ImageWriteParam param = w.getDefaultWriteParam();
		param.setCompressionMode(ImageWriteParam.MODE_EXPLICIT);
		param.setCompressionQuality(0.95f);
		try (ImageOutputStream os = ImageIO.createImageOutputStream(file)) {
			w.setOutput(os);
			w.write(null, new IIOImage(img, null, null), param);
		} finally {
			w.dispose();
		}
	}

	static void deleteTree(Path dir) {
		try (Stream<Path> s = Files.walk(dir)) {
			s.sorted(Comparator.reverseOrder()).forEach(q -> q.toFile().delete());
		} catch (IOException ignored) {
		}
	}

	static void say(Minecraft mc, Component msg) {
		mc.execute(() -> {
			if (mc.player != null) mc.player.displayClientMessage(msg, false);
		});
	}
}
