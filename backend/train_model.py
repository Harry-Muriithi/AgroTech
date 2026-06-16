import tensorflow as tf
from tensorflow.keras.applications import MobileNetV2
from tensorflow.keras import layers, models
from tensorflow.keras.preprocessing.image import ImageDataGenerator
from tensorflow.keras.callbacks import ModelCheckpoint, EarlyStopping, ReduceLROnPlateau
import pickle
import os

# ── SETTINGS ──────────────────────────────────────────────
DATA_PATH = r"C:\Users\LENOVO\Desktop\AGRITECH PROJECT\data\raw\plantvillage dataset\color"
MODEL_SAVE = r"C:\Users\LENOVO\Desktop\AgroTECH\models\plant_model.h5"
LABELS_SAVE = r"C:\Users\LENOVO\Desktop\AgroTECH\models\class_labels.pkl"

IMG_SIZE = 160
BATCH_SIZE = 64
EPOCHS = 15
# ──────────────────────────────────────────────────────────

print("✅ Step 1: Loading dataset...")

train_gen = ImageDataGenerator(
    rescale=1./255,
    validation_split=0.2,
    rotation_range=20,
    width_shift_range=0.2,
    height_shift_range=0.2,
    zoom_range=0.2,
    horizontal_flip=True,
    fill_mode='nearest'
)

train_data = train_gen.flow_from_directory(
    DATA_PATH,
    target_size=(IMG_SIZE, IMG_SIZE),
    batch_size=BATCH_SIZE,
    class_mode='categorical',
    subset='training',
    shuffle=True
)

val_data = train_gen.flow_from_directory(
    DATA_PATH,
    target_size=(IMG_SIZE, IMG_SIZE),
    batch_size=BATCH_SIZE,
    class_mode='categorical',
    subset='validation',
    shuffle=False
)

print(f"✅ Step 2: Found {train_data.num_classes} disease classes")
print(f"   Training images:   {train_data.samples}")
print(f"   Validation images: {val_data.samples}")

# Save class labels
with open(LABELS_SAVE, 'wb') as f:
    pickle.dump(train_data.class_indices, f)
print("✅ Step 3: Class labels saved!")

# ── BUILD MODEL ───────────────────────────────────────────
print("✅ Step 4: Building AI model...")

base_model = MobileNetV2(
    input_shape=(IMG_SIZE, IMG_SIZE, 3),
    include_top=False,
    weights='imagenet'
)
base_model.trainable = False

model = models.Sequential([
    base_model,
    layers.GlobalAveragePooling2D(),
    layers.BatchNormalization(),
    layers.Dense(256, activation='relu'),
    layers.Dropout(0.4),
    layers.Dense(128, activation='relu'),
    layers.Dropout(0.2),
    layers.Dense(train_data.num_classes, activation='softmax')
])

model.compile(
    optimizer=tf.keras.optimizers.Adam(learning_rate=0.001),
    loss='categorical_crossentropy',
    metrics=['accuracy']
)

model.summary()

# ── CALLBACKS ─────────────────────────────────────────────
callbacks = [
    # Save best model automatically
    ModelCheckpoint(
        MODEL_SAVE,
        monitor='val_accuracy',
        save_best_only=True,
        verbose=1
    ),
    # Stop early if not improving
    EarlyStopping(
        monitor='val_accuracy',
        patience=4,
        restore_best_weights=True,
        verbose=1
    ),
    # Reduce learning rate when stuck
    ReduceLROnPlateau(
        monitor='val_loss',
        factor=0.3,
        patience=2,
        verbose=1
    )
]

# ── PHASE 1: TRAIN TOP LAYERS ─────────────────────────────
print("✅ Step 5: Phase 1 — Training top layers...")
history1 = model.fit(
    train_data,
    validation_data=val_data,
    epochs=EPOCHS,
    callbacks=callbacks,
    verbose=1
)

# ── PHASE 2: FINE TUNE ────────────────────────────────────
print("✅ Step 6: Phase 2 — Fine tuning base model...")
base_model.trainable = True

# Only unfreeze last 30 layers
for layer in base_model.layers[:-30]:
    layer.trainable = False

model.compile(
    optimizer=tf.keras.optimizers.Adam(learning_rate=0.0001),
    loss='categorical_crossentropy',
    metrics=['accuracy']
)

history2 = model.fit(
    train_data,
    validation_data=val_data,
    epochs=10,
    callbacks=callbacks,
    verbose=1
)

# ── DONE ──────────────────────────────────────────────────
final_acc = max(history2.history['val_accuracy']) * 100
print(f"\n🎉 Training Complete!")
print(f"✅ Best Validation Accuracy: {final_acc:.1f}%")
print(f"✅ Model saved to: {MODEL_SAVE}")
print(f"✅ Labels saved to: {LABELS_SAVE}")
print(f"\n🚀 Ready to build the backend API!")