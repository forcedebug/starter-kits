import fs from 'fs';
import path from 'path';
import { parse, ParseResult } from "papaparse";
import { AttackerEntry, TruePositiveCsv } from "./types";

export default class TruePositiveFetcher {

  truePositiveListUrl: string;
  truePositiveListPath: string;

  constructor(truePositiveListUrl: string, truePositiveListPath: string) {
    this.truePositiveListUrl = truePositiveListUrl;
    this.truePositiveListPath = truePositiveListPath;
  }

  private isValidEthereumAddress = (address: string): boolean => {
      const ethAddressRegex = /^0x[a-fA-F0-9]{40}$/;
      return ethAddressRegex.test(address);
  }

  private processParseResults = (results: ParseResult<TruePositiveCsv>, tpAttackers: string[]) => {
    results.data.forEach((attackerEntry: AttackerEntry) => {
      const attackerArray: string[] = attackerEntry.Attacker.split(",");

      attackerArray.forEach((attacker: string) => {
        attacker = attacker.trim();
        if (this.isValidEthereumAddress(attacker)) {
          tpAttackers.push(attacker.toLowerCase());
        }
      });
    });
  }

  private getTruePositiveListRemotely = (tpListUrl: string, tpAttackers: string[]) => {
    parse(tpListUrl, {
      download: true,
      header: true,
      skipEmptyLines: true,
      complete: (results: ParseResult<TruePositiveCsv>) => {
        if(results.errors.length) throw new Error("getTruePositiveListRemotely() failed.");
        this.processParseResults(results, tpAttackers);
      },
      error: (error: Error) => {
        throw new Error(`getTruePositiveListRemotely() failed. error: ${error.message}`);
      }
    });
  }

  private getTruePositiveListLocally = (tpListPath: string, tpAttackers: string[]) => {
    const resolvedTpListPath = path.resolve(__dirname, tpListPath);
    const tpListContent = fs.readFileSync(resolvedTpListPath, 'utf8');
  
    parse(tpListContent, {
      header: true,
      skipEmptyLines: true,
      complete: (results: ParseResult<TruePositiveCsv>) => {
        if(results.errors.length) throw new Error("getTruePositiveListLocally() failed.");
        this.processParseResults(results, tpAttackers);
      },
      error: (error: Error) => {
        throw new Error(`getTruePositiveListLocally() failed. error: ${error.message}`);
      }
    });
  };

  public getTruePositiveList = (
    attackers: Map<string, { origin: string; hops: number }>
  ) => {
    let truePositiveAttackers: string[] = [];
  
    try {
      this.getTruePositiveListRemotely(this.truePositiveListUrl, truePositiveAttackers);
    } catch(e) {
      console.error(`Error: ${e}`);
      try {
        this.getTruePositiveListLocally(this.truePositiveListPath, truePositiveAttackers);
      } catch (e) {
        console.log(`Both True Positive List fetching functions failed.`);
        console.error(`Error: ${e}`);
      }
    }
  
    truePositiveAttackers.forEach((attacker: string) => {
      const origin = "True Positive List";
      const hops = 0;

      if(!attackers.has(attacker)) attackers.set(attacker, { origin, hops });
    });
  }
}