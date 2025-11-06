import {
    Firestore
} from '@google-cloud/firestore';

// one constructor call == correct database straight away
const db = new Firestore({
    projectId: 'regualtor-wr', // GCP project
    databaseId: 'brand-submitter', // Firestore DB inside the project
    keyFilename: './sa-key.json', // same key you used before
});

const FROM_COLL = 'operations';
const TO_COLL = 'qpost-operations';

async function copyCollection(fromColl, toColl) {
    const srcSnap = await db.collection(fromColl).get();
    let batch = db.batch(),
        ops = 0;

    for (const doc of srcSnap.docs) {
        batch.set(db.collection(toColl).doc(doc.id), doc.data());
        if (++ops === 500) {
            await batch.commit();
            batch = db.batch();
            ops = 0;
        }
    }
    if (ops) await batch.commit();
    console.log(`Copied ${srcSnap.size} docs ${fromColl} → ${toColl}`);
}

copyCollection(FROM_COLL, TO_COLL).catch(console.error);
