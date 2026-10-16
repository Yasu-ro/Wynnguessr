package com.wynndle.panorama;

import com.google.gson.Gson;
import com.google.gson.JsonArray;
import com.google.gson.JsonElement;
import com.google.gson.JsonObject;
import net.minecraft.ChatFormatting;
import net.minecraft.client.Minecraft;
import net.minecraft.client.player.LocalPlayer;
import net.minecraft.core.BlockPos;
import net.minecraft.nbt.CompoundTag;
import net.minecraft.nbt.NbtAccounter;
import net.minecraft.nbt.NbtIo;
import net.minecraft.nbt.Tag;
import net.minecraft.network.chat.Component;
import net.minecraft.tags.BlockTags;
import net.minecraft.world.level.block.RenderShape;
import net.minecraft.world.level.block.state.BlockState;
import net.minecraft.world.level.storage.LevelResource;

import java.io.InputStream;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Duration;
import java.util.Base64;
import java.util.HashSet;
import java.util.Set;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import java.util.stream.Stream;

// Singleplayer only, in a downloaded copy of the world:
// - on joining, tells the site which chunks of the copy hold blocks (the grey
//   veil on the review map covers the others);
// - the tour key flies to every spot planned on the review map, one by one:
//   teleport, turn around once (Distant Horizons loads what is looked at),
//   wait, take the panorama, send it.
public class Tour {
	static final int SPIN_TICKS = 80;   // one full turn in 4 s
	static final int WAIT_TICKS = 100;  // then 5 s more before the picture
	static final int LOAD_TIMEOUT = 300; // a spot whose chunk never comes is skipped

	enum Step { IDLE, FETCHING, GOING, LANDING, SPINNING, WAITING, CAPTURING }

	static Step step = Step.IDLE;
	static int ticks;
	static int id, x, z;
	static volatile JsonArray fetched;
	static volatile boolean fetchFailed;
	static final Set<Integer> skipped = new HashSet<>();
	static Object coverageLevel;

	static void toggle(Minecraft mc) {
		if (step != Step.IDLE) {
			stop(mc, "tour stopped");
			return;
		}
		if (!mc.hasSingleplayerServer()) {
			say(mc, "the tour only works in singleplayer", ChatFormatting.RED);
			return;
		}
		if (WynndlePanorama.config.key.isEmpty()) {
			say(mc, "no key in config/wynndle-panorama.json", ChatFormatting.RED);
			return;
		}
		skipped.clear();
		say(mc, "tour started", ChatFormatting.GRAY);
		fetch();
	}

	static void stop(Minecraft mc, String why) {
		step = Step.IDLE;
		say(mc, why, ChatFormatting.GRAY);
	}

	static void fetch() {
		step = Step.FETCHING;
		fetched = null;
		fetchFailed = false;
		Thread t = new Thread(() -> {
			try {
				fetched = new Gson().fromJson(get("/api/capture/planned"), JsonArray.class);
			} catch (Exception e) {
				fetchFailed = true;
			}
		}, "wynndle-tour");
		t.setDaemon(true);
		t.start();
	}

	static void tick(Minecraft mc) {
		LocalPlayer p = mc.player;
		if (step != Step.IDLE && (p == null || mc.level == null || !mc.hasSingleplayerServer())) {
			step = Step.IDLE;
			return;
		}
		if (p != null && mc.level != coverageLevel) {
			coverageLevel = mc.level;
			if (mc.hasSingleplayerServer() && !WynndlePanorama.config.key.isEmpty()) sendCoverage(mc);
		}
		switch (step) {
			case IDLE -> { }
			case FETCHING -> {
				if (fetchFailed) { stop(mc, "tour stopped: site unreachable"); return; }
				if (fetched == null) return;
				// nearest spot first: short flights
				JsonObject best = null;
				double bestDist = Double.MAX_VALUE;
				for (JsonElement e : fetched) {
					JsonObject o = e.getAsJsonObject();
					if (skipped.contains(o.get("id").getAsInt())) continue;
					double dx = o.get("x").getAsInt() - p.getX(), dz = o.get("z").getAsInt() - p.getZ();
					if (dx * dx + dz * dz < bestDist) { bestDist = dx * dx + dz * dz; best = o; }
				}
				if (best == null) { stop(mc, "tour done: no planned spot left"); return; }
				id = best.get("id").getAsInt();
				x = best.get("x").getAsInt();
				z = best.get("z").getAsInt();
				say(mc, "flying to " + x + " " + z + " (" + (fetched.size() - skipped.size()) + " left)", ChatFormatting.GRAY);
				// from above, while the ground is not known yet
				p.getAbilities().flying = true;
				p.connection.sendCommand("tp @s " + (x + 0.5) + " " + (mc.level.getMaxY() - 2) + " " + (z + 0.5));
				step = Step.GOING;
				ticks = 0;
			}
			case GOING -> {
				// wait for the chunk, plus a moment so all its blocks are in
				if (++ticks > LOAD_TIMEOUT) {
					skipped.add(id);
					say(mc, x + " " + z + " skipped: not loaded", ChatFormatting.GOLD);
					fetch();
					return;
				}
				if (!mc.level.hasChunk(x >> 4, z >> 4) || ticks < 20) return;
				p.connection.sendCommand("tp @s " + (x + 0.5) + " " + ground(mc) + " " + (z + 0.5) + " 180 0");
				step = Step.LANDING;
				ticks = 0;
			}
			case LANDING -> {
				if (++ticks >= 10) { step = Step.SPINNING; ticks = 0; }
			}
			case SPINNING -> {
				ticks++;
				float yaw = 180f + 360f * ticks / SPIN_TICKS;
				p.setYRot(yaw);
				p.setXRot(0f);
				if (ticks >= SPIN_TICKS) { step = Step.WAITING; ticks = 0; }
			}
			case WAITING -> {
				if (++ticks >= WAIT_TICKS && !WynndlePanorama.busy) {
					WynndlePanorama.capture(mc, id);
					step = Step.CAPTURING;
				}
			}
			case CAPTURING -> {
				if (WynndlePanorama.busy) return;
				// sent: the spot is no longer planned; not sent: do not retry it in a loop
				if (!WynndlePanorama.lastSent) skipped.add(id);
				fetch();
			}
		}
	}

	// Feet height on the column: the first block from the top that stops a
	// player and can be seen (Wynncraft caps areas with invisible barriers),
	// leaves excepted (under a tree, not on it); water counts as ground.
	static int ground(Minecraft mc) {
		BlockPos.MutableBlockPos pos = new BlockPos.MutableBlockPos(x, mc.level.getMaxY(), z);
		for (int y = mc.level.getMaxY(); y > mc.level.getMinY(); y--) {
			pos.setY(y);
			BlockState s = mc.level.getBlockState(pos);
			if (!s.getFluidState().isEmpty()) return y + 1;
			if (s.blocksMotion() && s.getRenderShape() != RenderShape.INVISIBLE && !s.is(BlockTags.LEAVES)) return y + 1;
		}
		return mc.level.getMaxY() - 2;
	}

	// Region files start with 1024 offsets, one per chunk: not zero = saved.
	static final Pattern REGION = Pattern.compile("r\\.(-?\\d+)\\.(-?\\d+)\\.mca");

	static void sendCoverage(Minecraft mc) {
		Path dir = mc.getSingleplayerServer().getWorldPath(LevelResource.ROOT).resolve("region");
		Thread t = new Thread(() -> {
			JsonObject regions = new JsonObject();
			int chunks = 0;
			try (Stream<Path> files = Files.list(dir)) {
				for (Path f : (Iterable<Path>) files::iterator) {
					Matcher m = REGION.matcher(f.getFileName().toString());
					if (!m.matches()) continue;
					byte[] bits = chunkBits(f);
					if (bits == null) continue;
					for (byte v : bits) chunks += Integer.bitCount(v & 0xff);
					regions.addProperty(m.group(1) + "," + m.group(2), Base64.getEncoder().encodeToString(bits));
				}
				HttpRequest req = request("/api/coverage")
					.header("Content-Type", "application/json")
					.POST(HttpRequest.BodyPublishers.ofString(regions.toString()))
					.build();
				int status = HttpClient.newHttpClient().send(req, HttpResponse.BodyHandlers.ofString()).statusCode();
				say(mc, status == 200 ? "map coverage sent (" + chunks + " chunks)" : "map coverage not sent (error " + status + ")",
					status == 200 ? ChatFormatting.GRAY : ChatFormatting.GOLD);
			} catch (Exception e) {
				say(mc, "map coverage not sent (" + e.getClass().getSimpleName() + ")", ChatFormatting.GOLD);
			}
		}, "wynndle-coverage");
		t.setDaemon(true);
		t.start();
	}

	// One bit per chunk of the region, chunk (x & 31) + (z & 31) * 32, lowest
	// bit first, set when the chunk holds anything but air. The downloaded
	// world's generator is empty: a chunk the game made up itself (flying
	// outside the download, Distant Horizons) is saved too, but only air.
	static byte[] chunkBits(Path region) throws java.io.IOException {
		byte[] file = Files.readAllBytes(region);
		if (file.length < 4096) return null;
		byte[] bits = new byte[128];
		for (int i = 0; i < 1024; i++) {
			int offset = ((file[i * 4] & 0xff) << 16) | ((file[i * 4 + 1] & 0xff) << 8) | (file[i * 4 + 2] & 0xff);
			if (offset != 0 && hasBlocks(file, offset * 4096)) bits[i >> 3] |= (byte) (1 << (i & 7));
		}
		return bits;
	}

	static boolean hasBlocks(byte[] file, int at) {
		try {
			int length = ((file[at] & 0xff) << 24) | ((file[at + 1] & 0xff) << 16) | ((file[at + 2] & 0xff) << 8) | (file[at + 3] & 0xff);
			int type = file[at + 4];
			InputStream raw = new java.io.ByteArrayInputStream(file, at + 5, length - 1);
			InputStream in = switch (type) {
				case 1 -> new java.util.zip.GZIPInputStream(raw);
				case 2 -> new java.util.zip.InflaterInputStream(raw);
				case 3 -> raw;
				default -> null; // stored elsewhere or rare compression: count it
			};
			if (in == null) return true;
			CompoundTag chunk = NbtIo.read(new java.io.DataInputStream(in), NbtAccounter.unlimitedHeap());
			for (Tag section : chunk.getListOrEmpty("sections")) {
				for (Tag state : ((CompoundTag) section).getCompoundOrEmpty("block_states").getListOrEmpty("palette")) {
					String name = ((CompoundTag) state).getStringOr("Name", "minecraft:air");
					if (!name.equals("minecraft:air") && !name.equals("minecraft:void_air") && !name.equals("minecraft:cave_air")) return true;
				}
			}
			return false;
		} catch (Exception e) {
			return false;
		}
	}

	static HttpRequest.Builder request(String path) {
		return HttpRequest.newBuilder(URI.create(WynndlePanorama.config.url.replaceAll("/+$", "") + path))
			.timeout(Duration.ofSeconds(60))
			.header("X-Wynndle-Key", WynndlePanorama.config.key.trim())
			.header("User-Agent", "WynndlePanorama/1.4");
	}

	static String get(String path) throws Exception {
		HttpResponse<String> res = HttpClient.newHttpClient().send(request(path).GET().build(), HttpResponse.BodyHandlers.ofString());
		if (res.statusCode() != 200) throw new Exception("error " + res.statusCode());
		return res.body();
	}

	static void say(Minecraft mc, String text, ChatFormatting color) {
		WynndlePanorama.say(mc, Component.literal("Wynndle: " + text).withStyle(color));
	}
}
