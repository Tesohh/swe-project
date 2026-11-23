# Plan for the music model
The plan covers the data collection, the training, and the use of one audio model in the queue app.
Each part also teaches the machine learning ideas, so the build works as a course.

## Purpose
- Build one machine learning model for the queue app
- The model must label each song with a genre, a mood, and an energy value
- The model must tell if the audio is real music, or speech, noise, or a bad upload
- The model must give one vector per song, so the app can find songs with a near sound
- Teach the machine learning ideas in each step, so the build works as a course

## Background: what a model is
- A _model_ is software that learns its rules from examples, instead of rules that a person writes
- Most models today are a _neural network_, a web of simple math blocks with changeable numbers
- Each changeable number has the name _parameter_ or _weight_
- In _training_, the software shows the model many examples and changes the weights a little each time
- The weights slowly get values that put the model answers near the correct answers

## Model outputs
The model must give the following data for each song:
- The genre, for example "rock", "rap", or "jazz"
- One answer to one question: is the audio real music, or speech, noise, or a bad upload
- The mood, for example "calm", "sad", or "party"
- The energy, as one number from 0 to 1
- A _vector_, a short fixed list of numbers, that represents the sound of the song

A model that picks one answer from a fixed set does _classification_.
A model that gives a free number does _regression_.
The genre and the mood accept several answers at once, because one song can be "rap" and "party" at the same time.
Several answers at once have the name _multi-label classification_.

The vector output is different in one way:
- The training gives the meaning of each number in the vector
- Near sounds land on near vectors
- A representation of this kind has the name _embedding_
- Two songs with a near sound must get near vectors, so the app can find near songs fast

## Design: one model with five output parts
Do not train five models for the five outputs.
Train **one model** with one shared part and five output parts:
- The shared part hears the audio and extracts the features of the sound
- Each output part then reads the sound features and gives its one answer
- One pass on the audio serves all five outputs

The method has the name _multi-task learning_.
The shared part is the expensive part, and the output parts are cheap.
Multi-task learning often helps quality too, because the genre task teaches the model facts that the mood task then uses.

## Training data
A model learns only what the data shows.
The collection of examples with correct answers has the name _data set_.
Each example has the name _sample_, and each correct answer has the name _label_.

Sources:
- Use public collections of free music with tags, for example MTG-Jamendo and FMA
- Also collect audio without music, for example speech, podcasts, crowd noise, and silence
- Also collect bad uploads, for example loops of 10 hours and broken sound
- The target size is 20000 to 50000 songs, plus 5000 clips without music

The model needs the bad examples for two reasons:
- A model must see music and noise side by side to learn the difference
- A class with too many examples pulls the model toward the class, so keep the classes near balance

## Agent process
An _agent_ is a software program that uses a language model to do one task.
Each agent gives its answer in a fixed format, and code checks that format.
The agents give the commands, and standard tools download, cut, and check the audio.

Stages:
- _Collect_: agents make lists of search queries, one list per music type
- _Download_: the software gets the audio with yt-dlp and writes the files
- _Filter_: agents check the metadata of each file, for example the length
- _Deduplicate_: software removes doubles with an audio fingerprint
- _Label_: agents confirm or correct the genre and mood tags per song
- _Energy_: software measures the loudness and the beat speed, and gives the energy label
- _Review_: agents check a random sample of the labeled songs for wrong tags
- _Assemble_: code writes all labels into files with one fixed format
- Every stage writes its output to disk, so a stopped run can continue later

Lesson: data work is often 80 percent of a machine learning project.
The agent labels will contain errors, because agents make mistakes as any worker does.
Plan a manual review of 500 random samples, and count the label quality per source.
The data quality sets a hard limit on the model quality: bad data always gives a bad model.

## Model input and model type
Software hears in a different way than a person, so convert the audio first:
- Cut each window of audio into thin frequency bands
- Show the loudness per band as one picture
- The picture has the name _spectrogram_
- Time runs from left to right, and tone height runs from top to bottom
- The model reads the picture as a sequence of small tiles

The model type:
- Use a network of the _transformer_ type, which reads sound pictures, with about 95 million parameters
- A transformer links each tile to each other tile
  - The method has the name _attention_
  - Attention lets the model connect a drum hit at the start with a chord at the end
- Do not train the transformer from zero
- Start from a model that other people trained on a large public audio set
- Then train that model again on your own data
  - The second training has the name _fine-tuning_

Lesson: _transfer learning_ is the idea behind fine-tuning:
- A model built from zero needs millions of samples and weeks of machine time
- Fine-tuning needs 30000 samples and hours, because the model already knows how to hear
- Your data teaches only the last step: what the heard features mean for your tasks
- Transfer learning is the reason why a 10 GB graphics card is enough

## Training on the gaming PC
A modern graphics card does the training math hundreds of times faster than a processor.
The card has the name _GPU_.
The Nvidia software layer that drives the card has the name CUDA.

Setup:
- Use PyTorch, a training tool with full support for Nvidia cards
- Train on the PC with the RTX 3080 only, because fine-tuning needs that card
- Use _half precision_, numbers with less detail that take half the memory
- First train only the five output parts, with the shared part frozen
  - The first step shows fast if the output parts and the data are correct
- Then train all parts together for 10 to 20 epochs
  - One pass over the full data set has the name _epoch_
  - One epoch takes about 30 to 60 minutes on the 3080
- Hold a moving average of the weights for more stable learning
  - The device has the name EMA

The training loop, step by step:
1. Take a small group of samples from the data set
   - The group has the name _batch_, and a batch of 32 keeps the card memory small
2. Run the model on the batch, and the model gives its five answers per sample
3. Measure how far the answers sit from the labels
   - The distance has the name _loss_, and each output part has its own loss
4. Sum the five losses into one number
5. Compute for each weight the direction in which a small change lowers the loss
   - The computation has the name _backpropagation_
   - The list of weight changes has the name _gradient_
6. Move each weight a tiny step in the good direction
   - The step size has the name _learning rate_, and a typical value here is 0.00001
7. Take the next batch, and the losses fall slowly over thousands of steps

For the vector output, use one special method:
- The training pulls the vectors of songs with near tags together
- The training pushes the vectors of unlike songs away
- The method has the name _contrastive learning_
- Contrastive learning builds the near-sound rule into the vector space
- First distill the vector part from an existing music vector model, and then fine-tune the vector part
  - _Distill_ means: train the new model to copy the vectors of an older model

## Quality checks
A model can copy the training examples instead of the rules.
Then the model looks perfect on the training data, but the model fails on new songs.
This problem has the name _overfitting_.
The defense is simple: hold back part of the data as a separate set.

The held-back part has the name _validation set_, and 5 percent is a standard size.
Measure the model on the validation set after each epoch.

Each task needs a measure that matches the task type:
- Count the correct tags that the model finds for the genre and the mood
  - The share has the name _recall_
- Count how many of the model answers are correct
  - The share has the name _precision_
- Recall and precision work against each other
  - A model that answers "yes" too easily gets a low precision, so many wrong tags enter
  - A model that answers "no" too easily gets a low recall, so the model misses most tags
- Use the area under the precision-recall curve for multi-label tasks, because the classes differ in size
- Count the hard cases for the music test
  - Plain accuracy misleads when the classes differ in size
  - If 95 percent of the data is music, a model that answers "music" always still gets a 95 percent accuracy score
  - The accuracy score then hides the failure on the noise class

For the regression output:
- Count how well the energy values follow the labels in the order on a 0 to 1 scale
- The measure has the name _rank correlation_

For the vectors:
- Give the model one song from the validation set
- Check if the near songs come back first
- Count how many of the correct songs the search returns
- The measure has the name _recall at k_, where k is the number of returned songs

Lesson: save the measures after every epoch.
A curve that rises, holds flat, and then falls tells you when the model starts to copy the data instead of the rules.

## Storage of the vectors
- Use the pgvector extension for the postgres database
- Change the postgres service to the official image that includes the extension
- Add a new table `song_embeddings` with the following columns:
  - `song_id`: the song id
  - `model_id`: the model version, so a new model version can refresh the data later
  - The vector of 256 numbers, in half-size format to save space
  - The genre, the mood, the tag scores, the music test answer, and the energy
- Add an index for the fast near-vector search

Lesson: a comparison of all vectors one by one takes milliseconds at 30000 songs.
The full comparison costs seconds at millions of songs, so pgvector first builds a map of the vector space:
- The map keeps each vector near the neighboring vectors
- The search then touches only a small part of the data
- A map of this kind has the name _approximate nearest neighbor index_
- The pgvector variant has the name HNSW
- The word "approximate" means that the search can miss a result now and then, in exchange for speed
- The distance measure has the name _cosine similarity_
- The cosine measure checks the angle between two vectors, and the length of each vector stays out of the comparison

## Model use on two machines
A trained model is a file full of weights.
A separate program does the math with the weights on a card.
The second use of the model has the name _inference_, in contrast to training.
The Nvidia card speaks one instruction language, and the Intel Arc card speaks a different one.

Export and runtime:
- After training, export the model to one open format
  - The standard format has the name ONNX, and many runtime programs read the ONNX format
- One loading program then runs the model:
  - On the gaming PC, use the Nvidia runtime path
  - On the Intel PC, use the Intel runtime path, or one built on Vulkan
- The inference worker checks which card is present, and then picks the right mode
- Export two copies of the same model
  - One copy in half-size numbers for the Nvidia card
  - One copy in 8-bit numbers for the Intel card

Lesson: numbers with 8 bits instead of 32 bits make the model four times smaller.
The conversion has the name _quantization_.
Quantization often costs almost no quality, and a quantized model runs faster on a laptop-class graphics chip.

Roles of the two machines:
- The gaming PC does the training work, and the gaming PC also runs the model for use
- The Intel PC with the Arc graphics chip does the model use and the agent work, because the agents need only the processor

## Integration with the app
- The `songs` table already has columns for `genre`, `mood`, and `quality`
- After each song download, one background job sends the audio through the model
- The job writes all outputs and the vector to the database
- The model runs one time per song, and the app requests stay fast
- New features then read the stored data:
  - Block bad uploads before a bad song enters the queue
  - Filter a queue by genre
  - Order the queue in a smart way with the vectors and the mood data

## Order of work
1. Write the fixed format for the labeled data, and the code that checks the format
2. Build the agent process for one small trial set, with one genre plus speech
3. Collect about 10000 songs, and train the first model
   - Check the quality measures
   - Adjust the agents and the training
4. Grow the data set to 30000 songs plus the bad-upload set, then train again
5. Add the pgvector table, the background job, and the app endpoints
6. Add the export step to the training flow from day one
   - The export step makes sure that every model version runs on both machines

Lesson: each step gives a small model that you can test and study.
Begin at a small scale, look at the measures, and scale up after the measures look good.
A large training run with unchecked data wastes a day of machine time, and the failure shows only at the end.

## Small experiments for learning
Do the following experiments next to the main work, because the experiments teach fast:
- Train a tiny genre model on the free GTZAN set first
  - The GTZAN set has 1000 songs
  - The experiment teaches the full training loop in one hour
- Change the learning rate, and watch the loss curve
  - A rate set too high makes the loss jump
  - A rate set too low makes the loss crawl
- Look at one spectrogram picture per training run, and check the model errors by hand
  - Your eyes will see why the model fails on one case, and you learn what the model sees
- Load the model file from an epoch that overfits, and compare its answers with the good epoch
- Pick one known song, and study the ten songs that the vector search returns
  - Real search results teach more about an embedding than any chart

## Risks
- The agent labels will contain errors, so review a sample by hand
- Bad uploads come in endless new forms, so always add new bad examples to the data set
- The vector quality depends on the label quality, so check the vector search before you build features on the vectors
- Work with small trial runs first, because a big run with bad data wastes a day of machine time
